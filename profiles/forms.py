from django import forms

class UsernameSearchForm(forms.Form):
    username = forms.CharField(label='Username or Handle', max_length=150)

