import aiohttp

async def update_nodes(db_snap:bytes,dependent_nodes:list[str],api_key:str):
        """
        Updates list of dependent nodes with port
        """
        connector = aiohttp.TCPConnector(ssl=False)
        session = aiohttp.ClientSession(connector=connector,connector_owner=True)
        form = aiohttp.FormData()
        form.add_field(
            'file',
            db_snap,
            filename="users.db",
            content_type='application/octet-stream'
        )
        for s in dependent_nodes:
            await session.post(f"https://{s}/update",data=form,headers={"X-API-Key": api_key})
        await session.close()

async def get_subs(user_id:str,dependent_nodes:list[str],api_key:str):
        """
        Updates list of dependent nodes with port
        """
        connector = aiohttp.TCPConnector(ssl=False)
        session = aiohttp.ClientSession(connector=connector,connector_owner=True)
        links = []

        for s in dependent_nodes:
            resp = await session.get(f"https://{s}/sub/get/{user_id}",headers={"X-API-Key": api_key})
            if resp.status == 200:
                data = await resp.json()
                links.append(data['link'])

        await session.close()
        return links