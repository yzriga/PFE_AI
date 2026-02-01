from django.contrib import admin
from .models import Document, Question, Answer, Session

admin.site.register(Document)
admin.site.register(Question)
admin.site.register(Answer)
admin.site.register(Session)