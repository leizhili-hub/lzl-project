from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django.shortcuts import get_object_or_404
from .models import TestCase, TestCaseStep, TestCaseAttachment, TestCaseComment, TestCaseExecution
from .serializers import (
    TestCaseSerializer, TestCaseCreateSerializer, TestCaseUpdateSerializer,
    TestCaseExecutionSerializer, TestCaseExecutionCreateSerializer
)
from apps.projects.models import Project
from apps.core.mixins import ProjectScopedMixin



class TestCaseListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = TestCase.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['priority', 'status', 'test_type', 'project']
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'updated_at', 'priority', 'sort_order']
    # sort_order 升序优先（业务顺序：墨刀采纳的用例按生成顺序 1,2,3... 排列），
    # 其次 created_at 升序（同 sort_order 时早创建的在前），保证用例库顺序与生成顺序一致。
    ordering = ['sort_order', 'created_at', 'id']
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TestCaseCreateSerializer
        return TestCaseSerializer
    
    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('executions')
        
        # 版本筛选
        version = self.request.query_params.get('version', None)
        if version:
            qs = qs.filter(versions__id=version)
        
        # 功能模块筛选（含子孙模块：按父模块筛选时也能查到其下子模块的用例）
        feature_module = self.request.query_params.get('feature_module', None)
        if feature_module:
            from apps.feature_modules.models import FeatureModule as _FM
            fm_ids = {int(feature_module)}
            # 递归收集所有子孙模块 id
            stack = [int(feature_module)]
            while stack:
                pid = stack.pop()
                for cid in _FM.objects.filter(parent_id=pid).values_list('id', flat=True):
                    if cid not in fm_ids:
                        fm_ids.add(cid)
                        stack.append(cid)
            qs = qs.filter(feature_modules__id__in=fm_ids)
        
        # 测试点筛选
        test_point = self.request.query_params.get('test_point', None)
        if test_point:
            qs = qs.filter(test_point_id=test_point)
        
        # 按标签筛选（单值 tags=冒烟；多值逗号分隔 tags=冒烟,画布:P17 连胜入口，多标签为「且」关系，
        # 供测试用例页「用例类别 + 来源画布 + 来源文件夹」组合筛选复用同一参数）
        tag_filter = self.request.query_params.get('tags', None)
        if tag_filter:
            for _t in [x.strip() for x in tag_filter.split(',') if x.strip()]:
                qs = qs.filter(tags__contains=[_t])
        
        return qs.distinct()
    
    def perform_create(self, serializer):
        user = self.request.user
        project_id = self.request.data.get('project_id')
        
        # 获取用户有权限的项目
        accessible_projects = self.get_accessible_projects()
        
        if project_id:
            # 检查指定的项目是否存在且用户有权限
            try:
                project = accessible_projects.get(id=project_id)
            except Project.DoesNotExist:
                # 如果指定项目不存在或无权限，使用第一个可访问的项目
                project = accessible_projects.first()
                if not project:
                    # 如果用户没有任何项目，创建默认项目
                    project = Project.objects.create(
                        name="默认项目",
                        owner=user,
                        description='系统自动创建的默认项目'
                    )
        else:
            # 没有指定项目，使用第一个可访问的项目
            project = accessible_projects.first()
            if not project:
                # 如果用户没有任何项目，创建默认项目
                project = Project.objects.create(
                    name="默认项目",
                    owner=user,
                    description='系统自动创建的默认项目'
                )
        
        serializer.save(author=user, project=project)

class TestCaseDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    用例详情 / 编辑 / 删除。

    2026-09-20：查看放开（全员可见），但**改/删**仍限"我负责或参与的项目"。
    """
    queryset = TestCase.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def _deny_if_not_writable(self, instance):
        """用例所属项目必须是我能写的（负责人/成员/管理员）。"""
        writable = self.get_accessible_projects()   # = 可写项目集合
        if not writable.filter(id=instance.project_id).exists():
            return Response(
                {'error': '只有用例所属项目的负责人、项目成员或管理员可以修改/删除该用例'},
                status=status.HTTP_403_FORBIDDEN
            )
        return None

    def update(self, request, *args, **kwargs):
        denied = self._deny_if_not_writable(self.get_object())
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self._deny_if_not_writable(self.get_object())
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return TestCaseUpdateSerializer
        return TestCaseSerializer
    
    def perform_update(self, serializer):
        user = self.request.user
        project_id = self.request.data.get('project_id')
        
        if project_id:
            # 检查指定的项目是否存在且用户有权限
            accessible_projects = self.get_accessible_projects()
            try:
                project = accessible_projects.get(id=project_id)
                serializer.save(project=project)
            except Project.DoesNotExist:
                # 如果指定项目不存在或无权限，保持原项目不变
                serializer.save()
        else:
            # 没有指定项目，保持原项目不变
            serializer.save()


class TestCaseExecuteView(generics.CreateAPIView):
    """执行测试用例（通过/失败）"""
    serializer_class = TestCaseExecutionCreateSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def perform_create(self, serializer):
        testcase_id = self.kwargs.get('pk')
        testcase = get_object_or_404(TestCase, pk=testcase_id)
        serializer.save(
            testcase=testcase,
            executed_by=self.request.user
        )


class TestCaseExecutionListView(generics.ListAPIView):
    """查看测试用例执行历史"""
    serializer_class = TestCaseExecutionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        testcase_id = self.kwargs.get('pk')
        return TestCaseExecution.objects.filter(
            testcase_id=testcase_id
        ).select_related('executed_by').order_by('-executed_at')


class TestCaseImportView(ProjectScopedMixin, APIView):
    """
    批量导入测试用例（Excel 经前端解析后传 JSON 数组）。

    强制要求：
      - project_id（所属项目）：必填，且用户需有该项目的写入权限
      - version_ids（关联版本）：必填且至少 1 个，且必须全部归属于所选项目
    这两个值会应用到文件中的每一条用例；文件内的"关联项目 / 关联版本"列被忽略。
    """
    permission_classes = [permissions.IsAuthenticated]

    # 中文显示值 → 模型 code 的双向映射（同时接受中文与英文）
    PRIORITY_MAP = {
        '低': 'low', '中': 'medium', '高': 'high', '紧急': 'critical',
        'low': 'low', 'medium': 'medium', 'high': 'high', 'critical': 'critical',
    }
    STATUS_MAP = {
        '草稿': 'draft', '激活': 'active', '废弃': 'deprecated',
        'draft': 'draft', 'active': 'active', 'deprecated': 'deprecated',
    }
    TYPE_MAP = {
        '功能测试': 'functional', '集成测试': 'integration', 'API测试': 'api',
        'UI测试': 'ui', '性能测试': 'performance', '安全测试': 'security',
        'functional': 'functional', 'integration': 'integration', 'api': 'api',
        'ui': 'ui', 'performance': 'performance', 'security': 'security',
    }

    def _norm_list(self, value):
        """将 '、' 或 ',' 分隔的字符串 / 列表统一为字符串列表。"""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value).replace('、', ',').split(',') if v.strip()]

    def post(self, request):
        project_id = request.data.get('project_id')
        version_ids = request.data.get('version_ids') or []
        cases = request.data.get('cases') or []

        if not project_id:
            return Response({'error': '必须选择所属项目'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(version_ids, list) or len(version_ids) == 0:
            return Response({'error': '必须至少选择一个关联版本'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(cases, list) or len(cases) == 0:
            return Response({'error': '没有可导入的用例数据，请先上传包含用例的 Excel'}, status=status.HTTP_400_BAD_REQUEST)

        # 校验项目写入权限
        accessible = self.get_accessible_projects()
        try:
            project = accessible.get(id=project_id)
        except Project.DoesNotExist:
            return Response({'error': '项目不存在，或你没有该项目的写入权限'}, status=status.HTTP_403_FORBIDDEN)

        # 校验版本归属该项目
        from apps.versions.models import Version
        versions = list(Version.objects.filter(id__in=version_ids, projects=project))
        found_ids = {v.id for v in versions}
        invalid = [vid for vid in version_ids if vid not in found_ids]
        if invalid:
            return Response(
                {'error': f'以下版本不存在或未关联到所选项目：{invalid}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        created = 0
        errors = []
        from apps.feature_modules.models import FeatureModule, TestPoint

        for idx, item in enumerate(cases, start=1):
            title = (item.get('title') or '').strip()
            expected = (item.get('expected_result') or item.get('expectedResult') or '').strip()
            if not title:
                errors.append({'row': idx, 'error': '用例标题不能为空'})
                continue
            if not expected:
                errors.append({'row': idx, 'error': '预期结果不能为空'})
                continue

            priority = self.PRIORITY_MAP.get((item.get('priority') or '').strip(), 'medium')
            st = self.STATUS_MAP.get((item.get('status') or '').strip(), 'draft')
            ttype = self.TYPE_MAP.get(
                (item.get('test_type') or item.get('testType') or '').strip(), 'functional'
            )
            tags = self._norm_list(item.get('tags'))

            tc = TestCase.objects.create(
                project=project,
                title=title,
                description=(item.get('description') or '').strip(),
                preconditions=(item.get('preconditions') or '').strip(),
                steps=(item.get('steps') or '').strip(),
                expected_result=expected,
                priority=priority,
                status=st,
                test_type=ttype,
                source='manual',
                tags=tags,
                author=user,
            )
            tc.versions.set(versions)

            # 按名称解析功能模块 / 测试点（若模块不存在则自动创建，避免模块丢失）
            fm_names = self._norm_list(item.get('feature_modules') or item.get('featureModules'))
            fm_ids = []
            if fm_names:
                for name in fm_names:
                    clean_name = name.strip().strip('/')
                    if not clean_name or clean_name == '-':
                        continue
                    if len(clean_name) > 100:
                        clean_name = clean_name[:100]
                    fm, _ = FeatureModule.objects.get_or_create(
                        project=project,
                        name=clean_name,
                        defaults={
                            'description': '测试用例导入自动创建',
                            'created_by': user,
                        },
                    )
                    if versions:
                        fm.versions.add(*versions)
                    fm_ids.append(fm.id)
                if fm_ids:
                    tc.feature_modules.set(fm_ids)

            tp_name = (item.get('test_point') or item.get('testPoint') or '').strip()
            if tp_name and tp_name != '-' and fm_ids:
                first_fm = FeatureModule.objects.get(id=fm_ids[0])
                clean_tp = tp_name[:200]
                tp, _ = TestPoint.objects.get_or_create(
                    feature_module=first_fm,
                    name=clean_tp,
                    defaults={
                        'description': '测试用例导入自动创建',
                        'created_by': user,
                    },
                )
                tc.test_point = tp
                tc.save(update_fields=['test_point'])

            created += 1

        return Response({
            'message': f'成功导入 {created} 条测试用例' + (f'，{len(errors)} 条因数据不完整被跳过' if errors else ''),
            'created': created,
            'failed': len(errors),
            'errors': errors[:50],
        })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def testcase_source_tags(request):
    """聚合当前范围（project/version）内用例 tags 中的来源标签。

    墨刀采纳时会把来源写入 tags：画布:P{page_no} {page_name} / 文件夹:{folder}
    （见 apps/requirement_analysis/modao_views.py _adopt_one_case）。
    返回 {'canvases': [...], 'folders': [...]} 供测试用例页「来源画布/来源文件夹」筛选。
    """
    from apps.core.mixins import get_accessible_projects_for_user
    qs = TestCase.objects.filter(project__in=get_accessible_projects_for_user(request.user))
    project_id = request.query_params.get('project')
    version_id = request.query_params.get('version')
    if project_id:
        qs = qs.filter(project_id=project_id)
    if version_id:
        qs = qs.filter(versions__id=version_id)
    tags = set()
    for tag_list in qs.exclude(tags=[]).values_list('tags', flat=True):
        for t in (tag_list or []):
            if isinstance(t, str):
                tags.add(t)
    canvases = sorted(t for t in tags if t.startswith('画布:'))
    folders = sorted(t for t in tags if t.startswith('文件夹:'))
    return Response({'canvases': canvases, 'folders': folders})
