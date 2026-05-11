from django.urls import path

from health_check.views import MainView

app_name = "health_check"

urlpatterns = [
    path("<str:subset>/", MainView.as_view(), name="health_check_subset"),
]
