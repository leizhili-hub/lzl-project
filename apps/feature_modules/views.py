import logging
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from .models import FeatureModule, TestPoint
from .serializers import FeatureModuleSerializer, TestPointSerializer
from apps.projects.models import Project
from apps.core.mixins import ProjectScopedMixin, get_accessible_projects_for_user

logger = logging.getLogger('django')


class FeatureModuleListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    """功能模块列表和创建视图"""
    queryset = FeatureModule.objects.all()
    serializer_class = FeatureModuleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering = ['project', 'name']

    def get_queryset(self):
        qs = super().get_queryset()
        version_id = self.request.query_params.get('version_id')
        if version_id:
            qs = qs.filter(versions__id=version_id)
        # used_with_version=<vid>：返回该版本下至少被一条用例实际关联的模块。
        # 供测试用例页的功能模块下拉优先展示「真实在用」的模块（修复按版本分组时
        # 部分已用模块因归属其他版本而整个消失、用户筛不到的问题）。
        used_with_version = self.request.query_params.get('used_with_version')
        if used_with_version:
            qs = qs.filter(testcases__versions__id=used_with_version)
        return qs.distinct()

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError
        user = self.request.user
        project_id = self.request.data.get('project_id')
        name = self.request.data.get('name', '').strip()
        version_ids = self.request.data.get('version_ids', [])
        project = None
        if project_id:
            try:
                project = self.get_accessible_projects().get(id=project_id)
            except Project.DoesNotExist:
                raise ValidationError({'project_id': '没有权限访问该项目或项目不存在'})

        if not project:
            raise ValidationError({'project_id': '请选择所属项目'})

        # 防重：同一项目下同名功能模块直接返回已有的（幂等）
        if name:
            existing = FeatureModule.objects.filter(project=project, name=name).first()
            if existing:
                serializer.instance = existing
                if version_ids:
                    existing.versions.add(*version_ids)
                return

        instance = serializer.save(created_by=user, project=project)
        if version_ids:
            instance.versions.set(version_ids)


class FeatureModuleDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    功能模块详情 / 编辑 / 删除。

    2026-09-20：查看放开（全员可见），但**改/删**仍限"我负责或参与的项目"。
    """
    queryset = FeatureModule.objects.all()
    serializer_class = FeatureModuleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _deny_if_not_writable(self, instance):
        """模块所属项目必须是我能写的（负责人/成员/管理员）。"""
        writable = self.get_accessible_projects()   # = 可写项目集合
        if not writable.filter(id=instance.project_id).exists():
            return Response(
                {'error': '只有模块所属项目的负责人、项目成员或管理员可以修改/删除该模块'},
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

    def perform_update(self, serializer):
        instance = serializer.save()
        version_ids = self.request.data.get('version_ids')
        if version_ids is not None:
            instance.versions.set(version_ids)

    def perform_destroy(self, instance):
        """删除功能模块。补充记录请求来源（用户/IP），模块上下文由 models.py 的 pre_delete signal 记录。"""
        try:
            user = self.request.user
            user_name = getattr(user, 'username', None) or str(user.id)
            ip = self.request.META.get('HTTP_X_FORWARDED_FOR') or self.request.META.get('REMOTE_ADDR') or '?'
            logger.info(
                '[FEATURE_MODULE_DELETE_REQUEST] id=%s name=%r requester=%r(user_id=%s) ip=%s',
                instance.id, instance.name, user_name, getattr(user, 'id', None), ip,
            )
        except Exception as e:  # noqa: BLE001 日志失败不影响删除
            logger.warning('[FEATURE_MODULE_DELETE_REQUEST] 记录请求日志失败 id=%s err=%s',
                           getattr(instance, 'id', None), e)
        super().perform_destroy(instance)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_project_feature_modules(request, project_id):
    """获取指定项目的功能模块列表（支持 version_id 过滤只返回该版本关联的模块）"""
    # 查看放开：登录用户可查看任意项目的模块（项目列表已对全员可见）
    accessible_projects = get_accessible_projects_for_user(request.user)

    if not accessible_projects.filter(id=project_id).exists():
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    modules = FeatureModule.objects.filter(project_id=project_id)
    # 按版本过滤：返回已关联该版本 + 未关联任何版本的模块（避免游离模块丢失）
    version_id = request.query_params.get('version_id')
    if version_id:
        from django.db.models import Q
        modules = modules.filter(Q(versions__id=version_id) | Q(versions__isnull=True) | Q(versions=None)).distinct()
    modules = modules.order_by('name')
    from .serializers import FeatureModuleSerializer
    serializer = FeatureModuleSerializer(modules, many=True)
    return Response(serializer.data)


# ─── TestPoint Views ───

class TestPointListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    """测试点列表和创建视图"""
    serializer_class = TestPointSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['feature_module']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering = ['feature_module', 'name']

    def get_queryset(self):
        # 读取放开：全员可见全部项目下的测试点
        accessible_projects = self.get_visible_projects()
        accessible_modules = FeatureModule.objects.filter(project__in=accessible_projects)
        return TestPoint.objects.filter(feature_module__in=accessible_modules)

    def perform_create(self, serializer):
        user = self.request.user
        feature_module_id = self.request.data.get('feature_module_id')
        name = self.request.data.get('name', '').strip()
        feature_module = None
        if feature_module_id:
            try:
                accessible_modules = FeatureModule.objects.filter(
                    project__in=self.get_accessible_projects()
                )
                feature_module = accessible_modules.get(id=feature_module_id)
            except FeatureModule.DoesNotExist:
                pass

        # 防重：同一功能模块下同名测试点直接返回已有的（幂等）
        if name and feature_module:
            existing = TestPoint.objects.filter(feature_module=feature_module, name=name).first()
            if existing:
                serializer.instance = existing
                return

        serializer.save(created_by=user, feature_module=feature_module)


class TestPointDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    测试点详情 / 编辑 / 删除。

    2026-09-20：查看放开（全员可见），但**改/删**仍限"我负责或参与的项目"。
    """
    serializer_class = TestPointSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # 读取放开
        accessible_projects = self.get_visible_projects()
        accessible_modules = FeatureModule.objects.filter(project__in=accessible_projects)
        return TestPoint.objects.filter(feature_module__in=accessible_modules)

    def _deny_if_not_writable(self, instance):
        """测试点所属模块的项目必须是我能写的。"""
        writable = self.get_accessible_projects()
        module = instance.feature_module
        if module is None or not writable.filter(id=module.project_id).exists():
            return Response(
                {'error': '只有测试点所属项目的负责人、项目成员或管理员可以修改/删除该测试点'},
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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_module_test_points(request, module_id):
    """获取指定功能模块下的测试点列表"""
    # 查看放开：登录用户可查看任意模块的测试点
    accessible_projects = get_accessible_projects_for_user(request.user)
    accessible_modules = FeatureModule.objects.filter(project__in=accessible_projects)

    if not accessible_modules.filter(id=module_id).exists():
        return Response({'error': '功能模块不存在'}, status=status.HTTP_404_NOT_FOUND)

    test_points = TestPoint.objects.filter(feature_module_id=module_id).order_by('name')
    from .serializers import TestPointSerializer
    serializer = TestPointSerializer(test_points, many=True)
    return Response(serializer.data)
