"""Replaces the original Java Spring forms with Django form classes."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from core.admin_access import is_reserved_admin_username
from core.utils import moderation

from .models import ArchiveFile, Rubric


class RegistrationForm(UserCreationForm):
    """Handles user registration data formerly processed by Java controllers."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'password1', 'password2', 'email')

    def clean_email(self):
        email = self.cleaned_data.get('email', '')
        if email:
            email_norm = User.objects.normalize_email(email)
            if User.objects.filter(email__iexact=email_norm).exists():
                raise forms.ValidationError('Email уже используется')
            return email_norm
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Пользователь с таким именем уже существует')
        if is_reserved_admin_username(username):
            raise forms.ValidationError('Это имя зарезервировано')
        return username

    def save(self, commit: bool = True) -> User:
        """Persist the user and copy the email field supplied by the form."""

        user: User = super().save(commit=False)
        email = self.cleaned_data.get('email')
        if email:
            user.email = email
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """Authenticates users similar to the prior Java login form."""


class RubricForm(forms.ModelForm):
    """Collects rubric configuration data for archive categories."""

    class Meta:
        model = Rubric
        fields = ('name', 'slug', 'is_public', 'public_slug', 'is_text_mode', 'field_schema')
        widgets = {
            'field_schema': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        if name:
            moderation.ensure_text_allowed(name, field='name')
        return name


class ArchiveFileForm(forms.ModelForm):
    """Captures archive file metadata mirroring the Java DTO."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].required = False

    class Meta:
        model = ArchiveFile
        fields = ('rubric', 'title', 'status', 'data')
        widgets = {
            'rubric': forms.HiddenInput(),
            'data': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_title(self):
        title = self.cleaned_data.get('title', '')
        if title:
            moderation.ensure_text_allowed(title, field='title')
        return title

    def clean_status(self):
        return self.cleaned_data.get('status') or ArchiveFile.Status.KEEP

    def clean_data(self):
        data = self.cleaned_data.get('data')
        if data not in (None, ''):
            moderation.ensure_text_allowed(str(data), field='data')
        return data
