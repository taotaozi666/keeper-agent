"""显式启用的本地文件/元数据集成测试，不调用模型。"""

import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.models.artifact import Artifact
from app.models.conversation import (
    Conversation,
    ConversationDeletion,
    ConversationTurn,
    utcnow,
)
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.conversation_repository import ConversationRepository
from app.services.artifact_service import ArtifactService


@unittest.skipUnless(os.environ.get("KEEPER_TEST_MYSQL") == "1", "需要本地 MySQL")
class ArtifactMySQLTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_export_ownership_expiry_and_history(self):
        meta_mysql_client_manager.init()
        engine = meta_mysql_client_manager.engine
        repo = ConversationRepository(engine)
        cid = None
        try:
            await repo.initialize()
            with tempfile.TemporaryDirectory() as root:
                service = ArtifactService(engine, root)
                await service.initialize()
                async with repo.acquire(None, "文件集成测试") as (
                    session,
                    conversation,
                    turn,
                ):
                    cid = conversation.id
                    rows = [{"序号": i, "名称": "测试"} for i in range(150)]
                    result = await service.save_result(cid, turn.id, rows, "测试查询")
                    file = await service.export(cid, turn.id, result.id, "csv")
                    self.assertEqual(
                        len(
                            service.path(file)
                            .read_text(encoding="utf-8-sig")
                            .splitlines()
                        ),
                        151,
                    )
                    with self.assertRaises(FileNotFoundError):
                        await service.get("other-conversation", file.id)
                    await repo.finish(
                        session,
                        conversation,
                        turn,
                        {
                            "last_query": {
                                "state": {"query": "测试查询"},
                                "data": rows,
                                "query_result_id": result.id,
                            }
                        },
                        {
                            "type": "done",
                            "message": "完成",
                            "results": [{"query_result_id": result.id, "data": rows}],
                            "files": [{"id": file.id}],
                        },
                        1,
                    )
                history = await repo.history(cid)
                self.assertEqual(
                    len(history["turns"][0]["response"]["results"][0]["data"]), 100
                )
                await repo.set_deleted(cid)
                with self.assertRaises(FileNotFoundError):
                    await service.get(cid, file.id)
                await repo.set_deleted(cid, False)
                self.assertEqual((await service.get(cid, file.id)).id, file.id)
                async with AsyncSession(engine) as session:
                    await session.execute(
                        update(Artifact)
                        .where(Artifact.conversation_id == cid)
                        .values(expires_at=utcnow() - timedelta(seconds=1))
                    )
                    await session.commit()
                with self.assertRaises(TimeoutError):
                    await service.get(cid, file.id)
                await service.cleanup_expired()
                self.assertFalse(service.path(file).exists())
        finally:
            if cid:
                async with AsyncSession(engine) as session:
                    for model in (Artifact, ConversationDeletion, ConversationTurn):
                        await session.execute(
                            delete(model).where(model.conversation_id == cid)
                        )
                    await session.execute(
                        delete(Conversation).where(Conversation.id == cid)
                    )
                    await session.commit()
            await engine.dispose()

    async def test_readonly_transaction_and_streaming(self):
        from sqlalchemy import text

        dw_mysql_client_manager.init()
        try:
            async with dw_mysql_client_manager.session_factory() as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                repo = DWMySQLRepository(session)
                await repo.get_db_info()
                await repo.validate("SELECT 1 AS value")
                self.assertEqual(await repo.run("SELECT 1 AS value"), [{"value": 1}])
        finally:
            await dw_mysql_client_manager.engine.dispose()
