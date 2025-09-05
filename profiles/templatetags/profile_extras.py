from django import template

register = template.Library()

@register.filter
def get_account_for(accounts, profile):
    for account in accounts:
        if account.profile_id == profile.id and account.platform == profile.platform:
            return account
    return None

# profiles/__init__.py (make sure the templatetags module is loaded)
# create a templatetags folder in profiles/ and add __init__.py inside it