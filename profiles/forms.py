from django import forms

class UsernameSearchForm(forms.Form):
    PLATFORM_CHOICES = [
        ('Twitter', 'Twitter'),
        ('GitHub', 'GitHub'),
        ('Instagram', 'Instagram'),
        ('TikTok', 'TikTok'),
        ('Sherlock','Sherlock')
        # You can add more platforms here:
        # ('LinkedIn', 'LinkedIn'),
    ]

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter Username',
        })
    )
    
    platform = forms.ChoiceField(
        choices=PLATFORM_CHOICES,
        widget=forms.HiddenInput()  # Hidden because you're using clickable cards
    )
