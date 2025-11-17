from profiles.models import BehavioralAnalysis


def ensure_behavioral_record(profile):
    """
    Make sure a BehaviorAnalysis record exists for this profile.
    Called before behavioral analysis is queued.
    """
    obj, _ = BehavioralAnalysis.objects.get_or_create(profile=profile)
    return obj
