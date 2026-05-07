import { APIRequestContext, expect } from "@playwright/test";

export interface RefMap {
  [ref: string]: number;
}

export async function login(
  request: APIRequestContext,
  username: string,
  password: string,
  companyCode?: string
): Promise<string> {
  const formData = new URLSearchParams();
  formData.append("username", username);
  formData.append("password", password);
  formData.append("grant_type", "password");
  if (companyCode) formData.append("company_code", companyCode);

  const res = await request.post("/api/auth/login", {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    data: formData.toString(),
  });
  expect(res.ok(), `Login failed for ${username}: ${await res.text()}`).toBeTruthy();
  const body = await res.json();
  return body.access_token;
}

export async function postJson(
  request: APIRequestContext,
  token: string,
  url: string,
  body: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const res = await request.post(url, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
  expect(res.ok(), `POST ${url} failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return await res.json();
}

export async function getJson(
  request: APIRequestContext,
  token: string,
  url: string
): Promise<Record<string, unknown>> {
  const res = await request.get(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.ok(), `GET ${url} failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return await res.json();
}

export async function putJson(
  request: APIRequestContext,
  token: string,
  url: string,
  body: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const res = await request.put(url, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
  expect(res.ok(), `PUT ${url} failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return await res.json();
}

export async function deleteJson(
  request: APIRequestContext,
  token: string,
  url: string
): Promise<Record<string, unknown>> {
  const res = await request.delete(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.ok(), `DELETE ${url} failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return await res.json();
}

export async function expectStatus(
  request: APIRequestContext,
  token: string,
  method: "GET" | "POST" | "PUT" | "DELETE",
  url: string,
  expectedStatus: number,
  body?: Record<string, unknown>
): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const opts: any = { headers };
  if (body) opts.data = body;

  let res: Response;
  switch (method) {
    case "GET": res = await request.get(url, opts); break;
    case "POST": res = await request.post(url, opts); break;
    case "PUT": res = await request.put(url, opts); break;
    case "DELETE": res = await request.delete(url, opts); break;
  }
  expect(res.status(), `${method} ${url} expected ${expectedStatus}`).toBe(expectedStatus);
  return res;
}

export function materializeRefs(row: Record<string, any>, refs: RefMap): Record<string, any> {
  const out: Record<string, any> = { ...row };
  for (const [key, value] of Object.entries(row)) {
    if (key.endsWith("_ref") && typeof value === "string" && refs[value] !== undefined) {
      out[key.replace("_ref", "_id")] = refs[value];
      delete out[key];
    }
    if (key.endsWith("_refs") && Array.isArray(value)) {
      out[key.replace("_refs", "_ids")] = value
        .map((ref: string) => refs[ref])
        .filter(Boolean);
      delete out[key];
    }
  }
  return out;
}
