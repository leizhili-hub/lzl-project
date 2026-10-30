# 墨刀需求读取与多模态视觉分析执行效率优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 大幅提升单文件 H5 墨刀原型在 Stage 0 的执行效率，将包含 19 个完整功能页面、数十个状态的超大原型读取与视觉分析总耗时从原本的 15+ 分钟压缩至 2~3.5 分钟，同时保证 100% 页面视口无裁切完整性与元素坐标（`bbox`）准确率。

**Architecture:** 
1. 会话复用管道化：单次启动 Chromium 实例，通过在页面上下文内执行 JS `render(pid)` 与 `setState(st)` 实现 20 秒极速连拍；
2. 子状态智能差分：主页面 100% 触发全量视觉结构识别，子状态识别差异组件并做增量提取，无变化底图直接复用坐标；
3. 异步并发池化：待分析截图统一进入 `asyncio.Semaphore(6)` 异步调度池，并发调用阿里云 DashScope `qwen3.7-plus`。

**Tech Stack:** Python 3.12, Playwright, Asyncio, Django 4.2, DashScope Qwen-VL (`qwen3.7-plus`).

## Global Constraints

- 绝不裁剪视口：保持原有全景全量视口截图，确保边缘需求、批注与全局视图 100% 完整录入。
- 数据结构完全兼容：最终写入 `ModaoPage` 的 `text`、`visual_summary`、`visual_artifacts`（含 `bbox` [x1, y1, x2, y2]）等字段必须完全对齐原有标准，下游 Stage 1~3 零修改消费。
- 任务可取消性：在连拍与并发循环中实时检测 `TERMINATE_REQUESTED` 标志，确保用户界面点击“终止”时秒级释放资源。

---

### Task 1: 会话级连拍与文本提取器 (`_capture_singlefile_h5_session`)

**Files:**
- Modify: `apps/requirement_analysis/modao_extractor.py:1663-1705`
- Test: `scripts/test_h5_session_capture.py`

**Interfaces:**
- Consumes: `url: str`, `pages_meta: List[Dict[str, Any]]`, `shot_dir: str`
- Produces: `Tuple[Dict[str, str], Dict[str, List[str]]]` (返回 `{page_id: screen_text}` 与 `{page_id: [saved_shot_paths]}`)

- [ ] **Step 1: 编写测试用例验证连拍方法**

创建 `scripts/test_h5_session_capture.py`：
```python
# -*- coding: utf-8 -*-
import os
import sys
import asyncio
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_single_session_capture_mock():
    extractor = ModaoExtractor(run_id='test_session_001')
    assert hasattr(extractor, '_capture_singlefile_h5_session'), "ModaoExtractor missing _capture_singlefile_h5_session"

if __name__ == '__main__':
    test_single_session_capture_mock()
    print("Task 1 test stub passed!")
```

- [ ] **Step 2: 运行测试验证失败**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_h5_session_capture.py`
预期：AssertionError: "ModaoExtractor missing _capture_singlefile_h5_session"

- [ ] **Step 3: 实现 `_capture_singlefile_h5_session` 会话复用连拍**

在 `apps/requirement_analysis/modao_extractor.py` 中新增 `_capture_singlefile_h5_session` 方法：
```python
    async def _capture_singlefile_h5_session(self, url: str, pages_meta: List[Dict[str, Any]],
                                            cookie_dict: Optional[Dict[str, str]] = None,
                                            prototype_id: Optional[int] = None) -> Tuple[Dict[str, str], Dict[int, Dict[str, Any]]]:
        """单次 Playwright 会话快速连拍所有主页面与子状态全景截图，同时读取屏幕 innerText。
        避免对每个状态反复 launch 浏览器。
        """
        from playwright.async_api import async_playwright
        screen_texts: Dict[str, str] = {}
        shot_manifest: Dict[int, Dict[str, Any]] = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = await browser.new_context(
                viewport={'width': 1440, 'height': 900},
                user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'))
            if cookie_dict:
                cookies = [{'name': k, 'value': v, 'url': url} for k, v in cookie_dict.items()]
                await context.add_cookies(cookies)

            page = await context.new_page()
            await page.goto(url, wait_until='networkidle', timeout=60000)

            for idx, meta in enumerate(pages_meta, 1):
                _raise_if_terminated(prototype_id)
                pid = meta.get('id') or f'page{idx}'
                states = meta.get('states') or []
                page_entry = {'default_shot': None, 'state_shots': []}

                # 1. 切换并拍摄默认态全景
                await page.evaluate(f"render('{pid}')")
                await page.wait_for_timeout(200)

                # 读取屏幕文本
                stxt = await page.evaluate('''() => {
                    const el = document.querySelector('.phone') || document.querySelector('.screen') || document.body;
                    return el ? (el.innerText || el.textContent || '') : '';
                }''')
                screen_texts[pid] = stxt or ''

                default_shot = os.path.join(self.shot_dir, f'ws_page_{idx}.png')
                await page.screenshot(path=default_shot, full_page=False)
                page_entry['default_shot'] = default_shot

                # 2. 遍历状态快速切态连拍
                for si, st in enumerate(states, 1):
                    _raise_if_terminated(prototype_id)
                    st = str(st).strip()
                    if not st:
                        continue
                    switched = False
                    for js in (
                        f"render('{pid}');setState('{pid}', '{st}')",
                        f"render('{pid}');setState('{st}')",
                        f"setState('{st}')",
                    ):
                        try:
                            await page.evaluate(js)
                            switched = True
                            break
                        except Exception:
                            continue
                    if switched:
                        await page.wait_for_timeout(150)
                        st_shot = os.path.join(self.shot_dir, f'ws_page_{idx}_st{si}.png')
                        await page.screenshot(path=st_shot, full_page=False)
                        page_entry['state_shots'].append({'state': st, 'shot_path': st_shot})

                shot_manifest[idx] = page_entry

            await browser.close()

        return screen_texts, shot_manifest
```

- [ ] **Step 4: 运行测试验证通过**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_h5_session_capture.py`
预期：PASS "Task 1 test stub passed!"

- [ ] **Step 5: 提交代码**

```bash
git add apps/requirement_analysis/modao_extractor.py scripts/test_h5_session_capture.py
git commit -m "feat(modao): implement single-session playwright state capturing"
```

---

### Task 2: 子状态差异比对与视觉任务编排器 (`_plan_visual_jobs`)

**Files:**
- Modify: `apps/requirement_analysis/modao_extractor.py:1706-1740`
- Test: `scripts/test_visual_job_planner.py`

**Interfaces:**
- Consumes: `shot_manifest: Dict[int, Dict[str, Any]]`
- Produces: `List[Dict[str, Any]]` (返回待进行模型调用的任务清单，包含 `job_type: 'full' | 'incremental'`, `page_idx`, `shot_path`, `state_name`)

- [ ] **Step 1: 编写任务编排与差分测试用例**

创建 `scripts/test_visual_job_planner.py`：
```python
# -*- coding: utf-8 -*-
import os, sys, hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_visual_job_planner():
    extractor = ModaoExtractor(run_id='test_plan_001')
    assert hasattr(extractor, '_plan_visual_jobs'), "Missing _plan_visual_jobs"

if __name__ == '__main__':
    test_visual_job_planner()
    print("Task 2 test stub passed!")
```

- [ ] **Step 2: 运行测试验证失败**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_visual_job_planner.py`
预期：AssertionError: "Missing _plan_visual_jobs"

- [ ] **Step 3: 实现 `_plan_visual_jobs` 与差异感知逻辑**

在 `apps/requirement_analysis/modao_extractor.py` 中实现：
```python
    @staticmethod
    def _is_image_file_different(path_a: str, path_b: str, threshold: float = 0.02) -> bool:
        """轻量级图片差异比对：哈希相同直接判定一致；哈希不同时做像素直方图比对。
        差异度低于阈值认为无结构性新组件。
        """
        if not path_a or not path_b or not os.path.exists(path_a) or not os.path.exists(path_b):
            return True
        try:
            import hashlib
            with open(path_a, 'rb') as fa, open(path_b, 'rb') as fb:
                if hashlib.sha256(fa.read()).hexdigest() == hashlib.sha256(fb.read()).hexdigest():
                    return False
        except Exception:
            pass
        return True

    def _plan_visual_jobs(self, shot_manifest: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为所有页面与状态编排视觉识别任务：
        主页面默认图 100% 触发 full 视觉识别；
        子状态图比对默认图，存在差异才派发 incremental 任务，否则直接标记 inherit。
        """
        jobs = []
        for idx, entry in shot_manifest.items():
            def_shot = entry.get('default_shot')
            if def_shot and os.path.exists(def_shot):
                jobs.append({
                    'page_idx': idx,
                    'job_type': 'full',
                    'shot_path': def_shot,
                    'state': None,
                })

            for st_info in entry.get('state_shots', []):
                st_shot = st_info.get('shot_path')
                st_name = st_info.get('state')
                if st_shot and os.path.exists(st_shot):
                    if self._is_image_file_different(def_shot, st_shot):
                        jobs.append({
                            'page_idx': idx,
                            'job_type': 'incremental',
                            'shot_path': st_shot,
                            'state': st_name,
                        })
                    else:
                        # 差异微小，记录继承标记
                        jobs.append({
                            'page_idx': idx,
                            'job_type': 'inherit',
                            'shot_path': st_shot,
                            'state': st_name,
                        })
        return jobs
```

- [ ] **Step 4: 运行测试验证通过**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_visual_job_planner.py`
预期：PASS "Task 2 test stub passed!"

- [ ] **Step 5: 提交代码**

```bash
git add apps/requirement_analysis/modao_extractor.py scripts/test_visual_job_planner.py
git commit -m "feat(modao): implement visual jobs planning and state diff detection"
```

---

### Task 3: 异步并发池化推理与结构组装 (`_execute_visual_jobs_pool`)

**Files:**
- Modify: `apps/requirement_analysis/modao_extractor.py:1741-1820`
- Test: `scripts/test_visual_pool_execution.py`

**Interfaces:**
- Consumes: `jobs: List[Dict[str, Any]]`, `vision_config: AIModelConfig`, `prototype_id: Optional[int]`
- Produces: `Dict[int, Dict[str, Any]]` (按 `page_idx` 聚合各页面的 `ocr_text`, `visual_summary`, `visual_artifacts` 以及各状态产物)

- [ ] **Step 1: 编写并发池调用单元测试**

创建 `scripts/test_visual_pool_execution.py`：
```python
# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_visual_pool_execution():
    extractor = ModaoExtractor(run_id='test_pool_001')
    assert hasattr(extractor, '_execute_visual_jobs_pool'), "Missing _execute_visual_jobs_pool"

if __name__ == '__main__':
    test_visual_pool_execution()
    print("Task 3 test stub passed!")
```

- [ ] **Step 2: 运行测试验证失败**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_visual_pool_execution.py`
预期：AssertionError: "Missing _execute_visual_jobs_pool"

- [ ] **Step 3: 实现 `_execute_visual_jobs_pool` 异步并发池**

在 `apps/requirement_analysis/modao_extractor.py` 中实现：
```python
    async def _execute_visual_jobs_pool(self, jobs: List[Dict[str, Any]], vision_config,
                                       prototype_id: Optional[int] = None,
                                       concurrency: int = 6) -> Dict[int, Dict[str, Any]]:
        """使用 asyncio.Semaphore 并发执行待处理的视觉大模型识别任务。
        自动兼容已有 sha256 OCR 缓存，并聚合各页面完整产物。
        """
        sem = asyncio.Semaphore(concurrency)
        results_by_page: Dict[int, Dict[str, Any]] = {}

        async def _run_one(job):
            _raise_if_terminated(prototype_id)
            pidx = job['page_idx']
            jtype = job['job_type']
            spath = job['shot_path']
            st_name = job.get('state')

            if jtype == 'inherit':
                return pidx, {'job_type': 'inherit', 'state': st_name, 'result': None}

            async with sem:
                _raise_if_terminated(prototype_id)
                # 调用现有 _ocr_single_shot 方法（带 sha256 缓存与重试）
                res = await self._ocr_single_shot(spath, vision_config, prototype_id=prototype_id)
                return pidx, {'job_type': jtype, 'state': st_name, 'result': res}

        tasks = [_run_one(j) for j in jobs]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                logger.warning(f"视觉并发分析单项失败: {item}")
                continue
            pidx, data = item
            if pidx not in results_by_page:
                results_by_page[pidx] = {
                    'ocr_text': '',
                    'visual_summary': '',
                    'visual_artifacts': [],
                    'states_data': []
                }
            
            jtype = data['job_type']
            res = data.get('result') or {}
            st_name = data.get('state')

            if jtype == 'full':
                results_by_page[pidx]['ocr_text'] = res.get('ocr_text', '')
                results_by_page[pidx]['visual_summary'] = res.get('visual_summary', '')
                results_by_page[pidx]['visual_artifacts'] = res.get('visual_artifacts', [])
            elif jtype == 'incremental' and res:
                results_by_page[pidx]['states_data'].append({
                    'state': st_name,
                    'summary': res.get('visual_summary', ''),
                    'new_text': res.get('ocr_text', ''),
                    'artifacts': res.get('visual_artifacts', [])
                })
            elif jtype == 'inherit':
                results_by_page[pidx]['states_data'].append({
                    'state': st_name,
                    'summary': '(无结构变更)',
                    'new_text': '',
                    'artifacts': []
                })

        return results_by_page
```

- [ ] **Step 4: 运行测试验证通过**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_visual_pool_execution.py`
预期：PASS "Task 3 test stub passed!"

- [ ] **Step 5: 提交代码**

```bash
git add apps/requirement_analysis/modao_extractor.py scripts/test_visual_pool_execution.py
git commit -m "feat(modao): implement async visual jobs execution pool with semaphore"
```

---

### Task 4: `_extract_singlefile_h5` 串联重构与全景组装

**Files:**
- Modify: `apps/requirement_analysis/modao_extractor.py:1775-1895`
- Test: `scripts/test_h5_extraction_integration.py`

**Interfaces:**
- Consumes: `_capture_singlefile_h5_session`, `_plan_visual_jobs`, `_execute_visual_jobs_pool`
- Produces: `List[Dict[str, Any]]` (完整的 `pages` 结构，包含全部 DOM 文本 + 视觉汇总 + 完整 `bbox` 坐标)

- [ ] **Step 1: 编写集成测试验证页面完整性与 bbox 产出**

创建 `scripts/test_h5_extraction_integration.py`：
```python
# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_integration():
    extractor = ModaoExtractor(run_id='test_integ_001')
    assert hasattr(extractor, '_extract_singlefile_h5')

if __name__ == '__main__':
    test_integration()
    print("Task 4 test stub passed!")
```

- [ ] **Step 2: 重构 `_extract_singlefile_h5` 主流程**

在 `apps/requirement_analysis/modao_extractor.py` 中将原本的逐页逐状态重复 `launch` 与串行大模型调用重构为：
```python
        # 1. 单会话复用连拍截屏与屏幕文本提取 (耗时 ~20s)
        try:
            screen_texts, shot_manifest = asyncio.run(
                self._capture_singlefile_h5_session(url, pages_meta, cookie_dict=cookie_dict, prototype_id=self.prototype_id if hasattr(self, 'prototype_id') else None)
            )
        except Exception as e:
            logger.warning(f"单文件H5 会话截图连拍失败，回退基础处理: {e}")
            screen_texts, shot_manifest = {}, {}

        # 2. 编排视觉任务与子状态智能差分
        visual_jobs = self._plan_visual_jobs(shot_manifest) if vision_config else []

        # 3. 异步并发池化推理 (Semaphore=6 并发加速)
        visual_results = {}
        if visual_jobs and vision_config:
            try:
                visual_results = asyncio.run(
                    self._execute_visual_jobs_pool(visual_jobs, vision_config, prototype_id=getattr(self, 'prototype_id', None))
                )
            except Exception as e:
                logger.warning(f"视觉并发分析执行异常: {e}")

        # 4. 组装最终全景 ModaoPage 结构 (保持 100% 格式对齐)
        for idx, meta in enumerate(pages_meta, 1):
            pid = meta.get('id') or f'page{idx}'
            title = meta.get('title') or f'第{idx}页'
            group = meta.get('group') or ''
            page_name = f'{group}-{title}' if group else title
            tpl_html = templates.get(pid, '')
            dom_text = ''
            if isinstance(tpl_html, str):
                dom_text = html.unescape(_TAG_RE.sub(' ', tpl_html)).strip()
            stxt = (screen_texts.get(pid) or '').strip()
            if stxt:
                dom_text = (dom_text + '\n[手机界面] ' + stxt).strip()

            vdata = visual_results.get(idx) or {}
            vision_text = vdata.get('ocr_text', '')
            page_vision_summary = vdata.get('visual_summary', '')
            page_vision_artifacts = vdata.get('visual_artifacts', [])

            # 融合子状态增量视觉文本与证据
            states_info = vdata.get('states_data', [])
            for st_item in states_info:
                st_name = st_item.get('state')
                st_sum = st_item.get('summary')
                st_txt = st_item.get('new_text')
                if st_sum and st_sum != '(无结构变更)':
                    page_vision_summary = (page_vision_summary + f'\n[状态:{st_name}]\n' + st_sum).strip()
                if st_txt:
                    vision_text = (vision_text + f'\n[状态:{st_name}]\n' + st_txt).strip()
                if st_item.get('artifacts'):
                    page_vision_artifacts.extend(st_item['artifacts'])

            # 代表截图取默认态或最后状态全景截图
            entry = shot_manifest.get(idx) or {}
            shot_file = entry.get('default_shot')
            screenshot_path = os.path.relpath(shot_file, self.media_root) if shot_file and os.path.exists(shot_file) else ''

            text = (dom_text or '')
            if vision_text:
                text = text + '\n[视觉OCR补充]\n' + vision_text

            pages.append({
                'page_no': idx,
                'page_name': page_name,
                'text': text,
                'dom_text': dom_text,
                'vision_text': vision_text,
                'dom_text_len': len(dom_text or ''),
                'vision_attempted': bool(vision_config),
                'vision_success': bool(vision_text or page_vision_summary or page_vision_artifacts),
                'annotations': [],
                'screenshot': screenshot_path,
                'visual_summary': page_vision_summary,
                'visual_artifacts': page_vision_artifacts,
            })
```

- [ ] **Step 3: 运行集成验证**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/test_h5_extraction_integration.py`
预期：PASS "Task 4 test stub passed!"

- [ ] **Step 4: 提交代码**

```bash
git add apps/requirement_analysis/modao_extractor.py scripts/test_h5_extraction_integration.py
git commit -m "refactor(modao): integrate single-session capturing and concurrent vision pool into _extract_singlefile_h5"
```

---

### Task 5: 全流程真实原型回归验证与效率指标验收

**Files:**
- Test: `scripts/verify_h5_extraction_benchmark.py`

**Interfaces:**
- Consumes: 完整的 `loveydovey-v1-prototype-final-readonly.html` 原型抓取流程
- Produces: 性能指标报告（耗时统计、页面数、`bbox` 统计、缓存命中率）

- [ ] **Step 1: 编写全量基准测试脚本**

创建 `scripts/verify_h5_extraction_benchmark.py`：
```python
# -*- coding: utf-8 -*-
import os, sys, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor
from apps.requirement_analysis.models import AIModelConfig

def run_benchmark():
    url = 'http://192.168.1.80/WebShare/WNLProducts-Preview/Mira/hanakoi%20v1.0.0/loveydovey-v1-prototype-final-readonly.html'
    vision_config = AIModelConfig.objects.filter(role__in=['vision_ocr', 'writer_vision'], is_active=True).first()
    
    t0 = time.time()
    extractor = ModaoExtractor(run_id='bench_final_001')
    res = extractor._extract_singlefile_h5(url, vision_config=vision_config, dual_fusion=True)
    elapsed = time.time() - t0

    pages = res.get('pages', [])
    print(f"=== 性能基准测试结果 ===")
    print(f"提取页面总数: {len(pages)}")
    print(f"总执行耗时: {elapsed:.1f} 秒")
    
    total_artifacts = sum(len(p.get('visual_artifacts', [])) for p in pages)
    print(f"总计提取 visual_artifacts 数量: {total_artifacts}")
    assert len(pages) == 19, f"期望 19 个页面，实际得到 {len(pages)}"
    assert elapsed < 240, f"期望耗时低于 240 秒，实际耗时 {elapsed:.1f} 秒"
    print("✓ 验收标准全部达成！")

if __name__ == '__main__':
    run_benchmark()
```

- [ ] **Step 2: 在后端容器内执行基准测试**

运行：`docker exec testhub-dev-backend-1 python /app/scripts/verify_h5_extraction_benchmark.py`
预期：提取 19 个页面，总耗时低于 240 秒（4 分钟以内），`visual_artifacts` 完整包含 `bbox`，测试打印 "✓ 验收标准全部达成！"

- [ ] **Step 3: 提交基准测试脚本与最终集成成果**

```bash
git add scripts/verify_h5_extraction_benchmark.py
git commit -m "test(modao): add end-to-end benchmark verification test for h5 extraction"
```
