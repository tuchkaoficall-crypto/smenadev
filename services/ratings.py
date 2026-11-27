"""Shared rating calculation for the bot and web panel."""


def apply_review_ratings(worker, reviews):
    """Only supplied criteria on visible reviews contribute to their averages."""
    reviews = [r for r in reviews if r.is_hidden is False]
    worker.total_reviews = len(reviews)
    for source, target in (
        ("rating", "rating"),
        ("punctuality", "punctuality_rating"),
        ("responsibility", "responsibility_rating"),
        ("quality", "quality_rating"),
        ("communication", "communication_rating"),
    ):
        values = [getattr(r, source) for r in reviews if getattr(r, source) is not None]
        setattr(worker, target, sum(values) / len(values) if values else 0.0)
