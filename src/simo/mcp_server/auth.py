from typing import Any, Optional
from asgiref.sync import sync_to_async
from simo.mcp_server.models import InstanceAccessToken
from simo.core.middleware import introduce_instance
from fastmcp.server.auth.auth import AccessToken, TokenVerifier



class DjangoTokenVerifier(TokenVerifier):

    async def verify_token(self, token: str) -> Optional[AccessToken]:

        def _load():
            access_token = InstanceAccessToken.objects.select_related(
                "instance"
            ).filter(
                token=token, date_expired=None
            ).first()
            if not access_token:
                return
            introduce_instance(access_token.instance)
            return access_token

        access_token = await sync_to_async(_load, thread_sensitive=True)()
        if not access_token:
            return None

        # Build a minimal AccessToken; scopes optional
        return AccessToken(
            token = token,
            client_id=str(access_token.instance.id),
            scopes=["simo:read", "simo:write"],
            claims={"instance_id": access_token.instance.id},
        )