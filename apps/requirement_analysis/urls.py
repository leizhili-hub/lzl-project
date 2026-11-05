from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RequirementDocumentViewSet,
    RequirementAnalysisViewSet,
    BusinessRequirementViewSet,
    GeneratedTestCaseViewSet,
    AnalysisTaskViewSet,
    AIModelConfigViewSet,
    PromptConfigViewSet,
    GenerationConfigViewSet,
    TestCaseGenerationTaskViewSet,
    ConfigStatusViewSet,
    GeneratedRequirementDocViewSet,
    RequirementAnalysisResultViewSet,
    ClarificationQuestionViewSet,
    upload_and_analyze,
    analyze_text,
    generate_requirement_doc,
    get_requirement_template,
    generate_knowledge_base,
    deep_question,
    refine_analysis,
)
from .modao_views import (
    modao_list, modao_create, modao_extract, modao_reset, modao_terminate, modao_struct, modao_clarify, modao_design,
    modao_update_pages,
    modao_generate_cases, modao_approve_case_generation, modao_approve_pages,
    modao_adoption_diff, modao_backfill_kb,
    modao_confirm, modao_smoke, modao_detail, modao_excel,     modao_edit,
    modao_page_edit, modao_ask, modao_adopt,
    modao_adopt_single,
    modao_log_viewer, modao_log_raw,
    modao_export_xmind, modao_import_xmind, modao_export_smoke_zentao,
    modao_page_reset,
    modao_folders, modao_select_by_folder,
)

# 创建DRF路由器
router = DefaultRouter()
router.register(r'documents', RequirementDocumentViewSet, basename='requirementdocument')
router.register(r'analyses', RequirementAnalysisViewSet, basename='requirementanalysis')
router.register(r'requirements', BusinessRequirementViewSet, basename='businessrequirement')
router.register(r'test-cases', GeneratedTestCaseViewSet, basename='generatedtestcase')
router.register(r'tasks', AnalysisTaskViewSet, basename='analysistask')
router.register(r'ai-models', AIModelConfigViewSet, basename='aimodelconfig')
router.register(r'prompts', PromptConfigViewSet, basename='promptconfig')
router.register(r'generation-config', GenerationConfigViewSet, basename='generationconfig')
router.register(r'testcase-generation', TestCaseGenerationTaskViewSet, basename='testcasegenerationtask')
router.register(r'config', ConfigStatusViewSet, basename='configstatus')
router.register(r'req-docs', GeneratedRequirementDocViewSet, basename='generatedrequirementdoc')
router.register(r'analysis-results', RequirementAnalysisResultViewSet, basename='requirementanalysisresult')
router.register(r'clarifications', ClarificationQuestionViewSet, basename='clarificationquestion')

app_name = 'requirement_analysis'

urlpatterns = [
    # DRF路由
    path('api/', include(router.urls)),

    # 特殊API端点
    path('api/upload-and-analyze/', upload_and_analyze, name='upload-and-analyze'),
    path('api/analyze-text/', analyze_text, name='analyze-text'),
    path('api/generate-req-doc/', generate_requirement_doc, name='generate-req-doc'),
    path('api/req-doc-template/', get_requirement_template, name='req-doc-template'),
    path('api/generate-knowledge-base/', generate_knowledge_base, name='generate-knowledge-base'),
    path('api/deep-question/', deep_question, name='deep-question'),
    path('api/refine-analysis/', refine_analysis, name='refine-analysis'),

    # 墨刀技能：需求读取与用例生成（5 阶段引导式工作流）
    path('api/modao/create/', modao_create, name='modao-create'),
    path('api/modao/list/', modao_list, name='modao-list'),
    path('api/modao/<int:pk>/extract/', modao_extract, name='modao-extract'),
    path('api/modao/<int:pk>/reset/', modao_reset, name='modao-reset'),
    path('api/modao/<int:pk>/terminate/', modao_terminate, name='modao-terminate'),
    path('api/modao/<int:pk>/struct/', modao_struct, name='modao-struct'),
    path('api/modao/<int:pk>/update-pages/', modao_update_pages, name='modao-update-pages'),
    path('api/modao/<int:pk>/page-reset/', modao_page_reset, name='modao-page-reset'),
    path('api/modao/<int:pk>/folders/', modao_folders, name='modao-folders'),
    path('api/modao/<int:pk>/select-by-folder/', modao_select_by_folder, name='modao-select-by-folder'),
    path('api/modao/<int:pk>/clarify/', modao_clarify, name='modao-clarify'),
    path('api/modao/<int:pk>/design/', modao_design, name='modao-design'),
    path('api/modao/<int:pk>/generate-cases/', modao_generate_cases, name='modao-generate-cases'),
    path('api/modao/<int:pk>/approve-case-generation/', modao_approve_case_generation, name='modao-approve-case-generation'),
    path('api/modao/<int:pk>/approve-pages/', modao_approve_pages, name='modao-approve-pages'),
    path('api/modao/<int:pk>/adoption-diff/', modao_adoption_diff, name='modao-adoption-diff'),
    path('api/modao/<int:pk>/backfill-kb/', modao_backfill_kb, name='modao-backfill-kb'),
    path('api/modao/<int:pk>/confirm/', modao_confirm, name='modao-confirm'),
    path('api/modao/<int:pk>/smoke/', modao_smoke, name='modao-smoke'),
    path('api/modao/<int:pk>/edit/', modao_edit, name='modao-edit'),
    # 画布级产物人工编辑（A2-c：单个画布独立分支）
    path('api/modao/<int:pk>/pages/<int:page_id>/edit/', modao_page_edit, name='modao-page-edit'),
    path('api/modao/<int:pk>/ask/', modao_ask, name='modao-ask'),
    path('api/modao/<int:pk>/', modao_detail, name='modao-detail'),
    path('api/modao/<int:pk>/export-xmind/', modao_export_xmind, name='modao-export-xmind'),
    path('api/modao/<int:pk>/export-smoke-zentao/', modao_export_smoke_zentao, name='modao-export-smoke-zentao'),
    path('api/modao/<int:pk>/import-xmind/', modao_import_xmind, name='modao-import-xmind'),
    path('api/modao/<int:pk>/excel/', modao_excel, name='modao-excel'),
    path('api/modao/<int:pk>/adopt/', modao_adopt, name='modao-adopt'),
    path('api/modao/<int:pk>/adopt-single/', modao_adopt_single, name='modao-adopt-single'),
    path('api/modao/log-viewer/', modao_log_viewer, name='modao-log-viewer'),
    path('api/modao/log-raw/', modao_log_raw, name='modao-log-raw'),
]
