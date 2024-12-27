from django.urls import path
from . import views

app_name = 'data_import'

urlpatterns = [
    path('accounts/librarian/upload/', views.data_upload, name='data-upload'),
]