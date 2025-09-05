from django import forms

PLATFORM_CHOICES = (
    ('Twitter', 'Twitter'),
    ('GitHub', 'GitHub'),
)

class UsernameSearchForm(forms.Form):
    username = forms.CharField(label='Username or Handle', max_length=150)
    platform = forms.ChoiceField(choices=PLATFORM_CHOICES, label='Platform')

