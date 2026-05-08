import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0IiwidXNlcl9pZCI6MSwiY29tcGFueV9pZCI6ImEyMzY3OWMwIiwicm9sZSI6InN1cGVydXNlciIsInBlcm1pc3Npb25zIjpbIioiXSwiZW5hYmxlZF9tb2R1bGVzIjpbImRhc2hib2FyZCIsImtwaSIsImFjY291bnRpbmciLCJhc3NldHMiLCJ0cmVhc3VyeSIsInNhbGVzIiwicG9zIiwiYnV5aW5nIiwic3RvY2siLCJtYW51ZmFjdHVyaW5nIiwicHJvamVjdHMiLCJjcm0iLCJzZXJ2aWNlcyIsImV4cGVuc2VzIiwidGF4ZXMiLCJhcHByb3ZhbHMiLCJyZXBvcnRzIiwiaHIiLCJhdWRpdCIsInJvbGVzIiwic2V0dGluZ3MiLCJkYXRhX2ltcG9ydCIsInNzbyIsImFuYWx5dGljcyIsInBlcmZvcm1hbmNlIiwiY2FzaGZsb3ciLCJjYW1wYWlnbnMiLCJtYXRjaGluZyIsImludGVyY29tcGFueSIsInN1YnNjcmlwdGlvbnMiLCJjcHEiLCJmb3JlY2FzdCIsInNob3BfZmxvb3IiXSwiYWxsb3dlZF9icmFuY2hlcyI6WzFdLCJ0eXBlIjoiY29tcGFueV91c2VyIiwidG9rZW5fdXNlIjoiYWNjZXNzIiwiZXhwIjoxNzc4MTgyNDI4LCJpYXQiOjE3NzgxODA2Mjh9.-_KCu-tswJG_mp9qEkueQ33K-kwAYQ7I_zPRm1mppLM"
        r = await client.get("http://localhost:8000/api/taxes/groups?branch_id=1", headers={"Authorization": f"Bearer {token}"})
        print(r.status_code)
        print(r.text)

asyncio.run(main())
