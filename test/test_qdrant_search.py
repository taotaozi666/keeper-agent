import asyncio

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository


async def main():
    embedding_client_manager.init()
    qdrant_client_manager.init()

    repo = ColumnQdrantRepository(qdrant_client_manager.client)

    # 1. 先把自然语言“销售额”转成向量
    embedding = await embedding_client_manager.client.aembed_query("品牌")

    # 2. 拿这个向量去 Qdrant 搜相似字段
    results = await repo.search(embedding, limit=5)

    # 3. 看最终召回哪些字段
    for i, item in enumerate(results, 1):
        print(
            f"{i}. id={item.id} "
            f"name={item.name} "
            f"desc={item.description} "
            f"table={item.table_id}"
        )

    await qdrant_client_manager.close()


asyncio.run(main())