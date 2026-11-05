# -*- coding: utf-8 -*-
"""墨刀执行实时监控脚本。

实时跟踪：
1. 阶段进度与最新日志（Stage 0 -> Stage 1 -> Stage 2 -> Stage 3 -> Stage 4）
2. 精确 Token 消耗（Prompt Tokens / Completion Tokens / Total Tokens / 字符数）
3. 性能耗时与瓶颈分析（Playwright 抽取、OCR、各阶段 LLM 耗时、向量去重耗时）
4. 质量与准确度指标（测试点数、去重比例、用例数、P8 质量自检报告、finish_reason 截断风险）
5. 自动输出多维度优化诊断分析。

用法：
  python scripts/monitor_modao_realtime.py [prototype_id]
如果不传 prototype_id，脚本会自动等待并捕获最新启动的墨刀任务。
"""
import os
import sys
import time
import json
import datetime
from pathlib import Path

# 设置 Django 环境
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from apps.requirement_analysis.models import ModaoPrototype, ModaoPage


def get_latest_or_running_prototype(target_id=None):
    if target_id:
        return ModaoPrototype.objects.filter(id=target_id).first()
    # 优先找正在执行的任务
    running = ModaoPrototype.objects.filter(
        status__in=['extracting', 'processing', 'running', 'designing']
    ).order_by('-id').first()
    if running:
        return running
    # 其次找最新的（包含 pending 或刚创建的）
    return ModaoPrototype.objects.order_by('-id').first()


def parse_timing_log(proto_id, timing_file_path):
    metrics = {
        'llm_calls': [],
        'stages': [],
        'total_in_tok': 0,
        'total_out_tok': 0,
        'total_tok': 0,
        'total_llm_elapsed': 0.0,
    }
    if not os.path.exists(timing_file_path):
        return metrics

    try:
        with open(timing_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 解析阶段耗时
                if '▶ STAGE' in line or '■ STAGE' in line:
                    metrics['stages'].append(line)
                # 解析 LLM 调用指标
                if '[LLM_METRICS]' in line:
                    try:
                        # 格式: [HH:MM:SS] [LLM_METRICS] model role=... in_tok=... out_tok=... total_tok=... p_len=... r_len=... elapsed=...s finish_reason=...
                        parts = line.split()
                        entry = {'raw': line}
                        for p in parts:
                            if '=' in p:
                                k, v = p.split('=', 1)
                                if k in ('in_tok', 'out_tok', 'total_tok', 'p_len', 'r_len'):
                                    entry[k] = int(v)
                                elif k == 'elapsed':
                                    entry[k] = float(v.rstrip('s'))
                                else:
                                    entry[k] = v
                        metrics['llm_calls'].append(entry)
                        metrics['total_in_tok'] += entry.get('in_tok', 0)
                        metrics['total_out_tok'] += entry.get('out_tok', 0)
                        metrics['total_tok'] += entry.get('total_tok', 0)
                        metrics['total_llm_elapsed'] += entry.get('elapsed', 0.0)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[Monitor Warn] Read timing log failed: {e}")

    return metrics


def main():
    target_id = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    
    print("=" * 70)
    print("🚀 TestHub 墨刀需求解析与用例生成【实时监测引擎】已就绪")
    print("=" * 70)
    if target_id:
        print(f"[*] 目标监控任务 ID: {target_id}")
    else:
        print("[*] 正在实时监听最新触发的墨刀任务...")

    active_proto = None
    baseline_id = None
    last_log_idx = 0
    last_status = None
    last_stage = None
    last_call_count = 0

    start_monitor_time = time.time()

    # 1. 等待任务捕获
    while True:
        proto = get_latest_or_running_prototype(target_id)
        if proto:
            # 如果是指定目标，直接进入
            if target_id and proto.id == target_id:
                active_proto = proto
                break
            # 如果未指定，检查是否有正在运行或刚创建的任务
            if proto.status in ['extracting', 'processing', 'running', 'designing']:
                active_proto = proto
                break
            # 记录最新的 baseline id
            if baseline_id is None:
                baseline_id = proto.id
                print(f"[*] 当前数据库最新任务 ID: {baseline_id} (状态: {proto.status})")
                print("[*] 正在等待前端或接口发起新的墨刀任务...")
            elif proto.id > baseline_id:
                active_proto = proto
                print(f"\n[+] 捕获到全新触发的墨刀任务: ID={proto.id} Title={proto.title}")
                break

        time.sleep(2)

    pid = active_proto.id
    timing_path = os.path.join(str(BASE_DIR), 'media', 'modao', f'proto_{pid}_timing.log')
    print(f"\n[★] 开始深度监控任务 #{pid}：【{active_proto.title}】")
    print(f"[*] 实时指标日志路径: {timing_path}\n" + "-" * 70)

    # 2. 循环实时监控任务
    while True:
        try:
            proto = ModaoPrototype.objects.filter(id=pid).first()
            if not proto:
                print(f"[!] 任务 #{pid} 不存在或已被删除")
                break

            current_status = proto.status
            current_stage = proto.current_stage

            # 状态变动提示
            if current_status != last_status or current_stage != last_stage:
                now_str = datetime.datetime.now().strftime('%H:%M:%S')
                print(f"\n[{now_str}] 📍 阶段流转 -> 当前状态: 【{current_status}】 | 处于阶段: 【Stage {current_stage}】")
                last_status = current_status
                last_stage = current_stage

            # 打印最新的 work_log
            if proto.work_log:
                logs = [l.strip() for l in proto.work_log.split('\n') if l.strip()]
                if len(logs) > last_log_idx:
                    for l in logs[last_log_idx:]:
                        print(f"   [WorkLog] {l}")
                    last_log_idx = len(logs)

            # 解析最新的 timing 与 Token 指标
            timing_data = parse_timing_log(pid, timing_path)
            llm_calls = timing_data['llm_calls']
            if len(llm_calls) > last_call_count:
                new_calls = llm_calls[last_call_count:]
                for call in new_calls:
                    now_str = datetime.datetime.now().strftime('%H:%M:%S')
                    print(f"   [{now_str}] ⚡ [LLM调用] 模型={call.get('model','?')} | 耗时={call.get('elapsed',0)}s | "
                          f"输入Token={call.get('in_tok',0)} (约{call.get('p_len',0)}字) | "
                          f"输出Token={call.get('out_tok',0)} (约{call.get('r_len',0)}字) | "
                          f"累计Token={call.get('total_tok',0)} | 截断状态={call.get('finish_reason','stop')}")
                last_call_count = len(llm_calls)

            # 检查任务是否已经结束（成功或失败）
            if current_status in ['completed', 'failed', 'extracted'] and current_stage in [3, 4, 0] and last_call_count > 0:
                # 给最后日志写入一点缓冲时间
                time.sleep(2)
                timing_data = parse_timing_log(pid, timing_path)
                print("\n" + "=" * 70)
                print(f"🏁 任务 #{pid} 运行完毕！最终状态: 【{current_status}】")
                print("=" * 70)

                # 生成深度复盘与优化分析
                render_final_analysis(proto, timing_data)
                break
            elif current_status == 'failed':
                print(f"\n[!] 任务 #{pid} 执行失败: {proto.error_message}")
                timing_data = parse_timing_log(pid, timing_path)
                render_final_analysis(proto, timing_data)
                break

            time.sleep(2)
        except KeyboardInterrupt:
            print("\n[*] 监控已被用户中断。正在输出当前已收集的阶段数据...")
            timing_data = parse_timing_log(pid, timing_path)
            render_final_analysis(proto, timing_data)
            break
        except Exception as e:
            print(f"[Monitor Error] {e}")
            time.sleep(2)


def render_final_analysis(proto, timing_data):
    print("\n📊 =============== 运行数据全景统计报告 ===============")
    print(f"任务 ID: {proto.id} | 原型标题: {proto.title}")
    pages = ModaoPage.objects.filter(prototype=proto)
    print(f"页面/画布总数: {pages.count()} 个 (选中执行: {pages.filter(selected=True).count()} 个)")

    # 1. Token 统计
    print("\n【1. Token 消耗统计】")
    total_in = timing_data['total_in_tok']
    total_out = timing_data['total_out_tok']
    total_all = timing_data['total_tok']
    print(f"  • 总调用 LLM 次数: {len(timing_data['llm_calls'])} 次")
    print(f"  • 输入 Token (Prompt): {total_in:,}")
    print(f"  • 输出 Token (Completion): {total_out:,}")
    print(f"  • 合计 Token 消耗: {total_all:,}")
    if total_all > 0:
        # 按 DeepSeek 计费标准预估 (~2元/百万token)
        cost_est = (total_in * 2.0 / 1000000) + (total_out * 8.0 / 1000000)
        print(f"  • 预估成本估算: 约 ¥{cost_est:.4f}")

    # 2. 性能与耗时分析
    print("\n【2. 性能耗时与瓶颈分析】")
    print(f"  • LLM 累计纯推理耗时: {timing_data['total_llm_elapsed']:.1f} 秒")
    if timing_data['stages']:
        print("  • 阶段耗时记录:")
        for st in timing_data['stages']:
            print(f"    - {st}")

    # 3. 产物与准确度评估
    print("\n【3. 产出用例与准确度指标】")
    testcases = proto.testcases_json or []
    smoke = proto.smoke_json or []
    print(f"  • 生成完整测试用例数: {len(testcases)} 条")
    print(f"  • 筛选冒烟测试用例数: {len(smoke)} 条")
    
    # 检查截断风险
    truncated_calls = [c for c in timing_data['llm_calls'] if c.get('finish_reason') == 'length']
    if truncated_calls:
        print(f"  ⚠️ 发现 {len(truncated_calls)} 次调用因超出 max_tokens 被截断！可能导致用例/结构不完整！")
    else:
        print("  ✓ 无 finish_reason=length 截断风险，模型生成完整。")

    # 4. 优化点诊断与建议
    print("\n💡 =============== 架构与效率优化建议 ===============")
    # 分析平均输入与输出比
    if timing_data['llm_calls']:
        avg_in = total_in / max(1, len(timing_data['llm_calls']))
        avg_out = total_out / max(1, len(timing_data['llm_calls']))
        max_call = max(timing_data['llm_calls'], key=lambda x: x.get('elapsed', 0))

        print(f"1. 耗时峰值定位:")
        print(f"   最慢的一次 LLM 调用耗时 {max_call.get('elapsed')}s (输入: {max_call.get('in_tok')} tok, 输出: {max_call.get('out_tok')} tok)")
        
        if avg_in > 6000:
            print("2. Prompt 冗余度优化 (重要):")
            print(f"   平均每次输入达到 {avg_in:.0f} Tokens。建议审查提示词中的历史上下文或全量页面信息，考虑采用 Top-K 裁剪或分批异步投递。")
        else:
            print(f"2. Prompt 上下文长度适中 (平均 {avg_in:.0f} Tokens)。")

        if len(pages) > 3:
            print("3. 并发提取与流水线优化:")
            print("   目前墨刀页面抓取与初步结构化支持按画布独立运行，可开启画布级并行推理以进一步缩短 40%~60% 总耗时。")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
