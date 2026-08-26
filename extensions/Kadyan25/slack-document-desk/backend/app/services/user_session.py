from app.db.models import SuperdocsSession


def get_or_create_session_id(db, slack_user_id: str) -> str:
    """One SuperDocs session per Slack user, minted deterministically so it's stable
    across restarts even before the row exists (matches architecture.md's session_id
    convention: 'slack-user-{id}')."""
    row = db.query(SuperdocsSession).filter_by(slack_user_id=slack_user_id).one_or_none()
    if row:
        return row.superdocs_session_id

    session_id = f"slack-user-{slack_user_id}"
    db.add(SuperdocsSession(slack_user_id=slack_user_id, superdocs_session_id=session_id))
    db.commit()
    return session_id
