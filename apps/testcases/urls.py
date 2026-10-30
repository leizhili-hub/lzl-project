from django.urls import path
from . import views

urlpatterns = [
    # 测试用例相关
    path('', views.TestCaseListCreateView.as_view(), name='testcase-list'),
    path('import/', views.TestCaseImportView.as_view(), name='testcase-import'),
    path('source-tags/', views.testcase_source_tags, name='testcase-source-tags'),
    path('<int:pk>/', views.TestCaseDetailView.as_view(), name='testcase-detail'),
    # 执行相关
    path('<int:pk>/execute/', views.TestCaseExecuteView.as_view(), name='testcase-execute'),
    path('<int:pk>/executions/', views.TestCaseExecutionListView.as_view(), name='testcase-execution-list'),
]