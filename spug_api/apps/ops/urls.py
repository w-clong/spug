# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from apps.ops.views import (BaselineRunView, BaselineView, ChangeLogView, ContextView,
                            DynamicGroupView, FactView, ModuleView, PipelineHostsView,
                            TemplateView, VariableView)

urlpatterns = [
    path('modules/', ModuleView.as_view()),
    path('context/', ContextView.as_view()),
    path('pipeline-hosts/', PipelineHostsView.as_view()),
    path('facts/', FactView.as_view()),
    path('variables/', VariableView.as_view()),
    path('dynamic-groups/', DynamicGroupView.as_view()),
    path('templates/', TemplateView.as_view()),
    path('baselines/', BaselineView.as_view()),
    path('baselines/run/', BaselineRunView.as_view()),
    path('changes/', ChangeLogView.as_view()),
]
