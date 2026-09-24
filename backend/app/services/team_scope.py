"""The active team of a request, as seen by the services.

``deps.get_team_user`` attaches it to the ``User`` for team-scoped routes. Services read
it through :func:`team_id_of`, which fails closed: an incident query without a team is a
programming error, never "all teams".
"""

from __future__ import annotations

import uuid

from app.models import User


class MissingTeamContext(RuntimeError):
    """A team-scoped service was called on a route without a team dependency."""


def team_id_of(actor: User) -> uuid.UUID:
    team_id = actor.active_team_id
    if team_id is None:
        raise MissingTeamContext("this operation needs an active team (use TeamUser)")
    return team_id
