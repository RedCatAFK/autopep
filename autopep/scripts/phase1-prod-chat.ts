import { randomUUID } from "node:crypto";
import { eq } from "drizzle-orm";
import { db } from "../src/server/db";
import { agentRuns, threads, user, workspaces } from "../src/server/db/schema";
import { startModalRun } from "../src/server/agent/modal-launcher";

async function main() {
  const ownerId = `phase1-prod-chat-${Date.now()}`;
  const workspaceId = randomUUID();
  const threadId = randomUUID();
  const runId = randomUUID();
  const prompt = `phase1-test-${Date.now()}: respond with the single word 'ready'.`;

  // Create user (better-auth user table)
  await db.insert(user).values({
    id: ownerId,
    name: "Phase1 prod chat",
    email: `${ownerId}@smoke.invalid`,
    emailVerified: false,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await db.insert(workspaces).values({ id: workspaceId, ownerId, name: "phase1 prod chat" });
  await db.insert(threads).values({ id: threadId, workspaceId, title: "main" });
  await db.update(workspaces).set({ activeThreadId: threadId }).where(eq(workspaces.id, workspaceId));
  await db.insert(agentRuns).values({
    id: runId,
    workspaceId,
    threadId,
    createdById: ownerId,
    prompt,
    model: "gpt-5",
    rootRunId: null,
    sdkStateJson: {},
    status: "queued",
    taskKind: "chat",
  });

  console.log("Run created:", runId);
  await startModalRun({ runId, threadId, workspaceId });
  console.log("Modal launched, polling for completion...");

  const start = Date.now();
  let final;
  while (Date.now() - start < 180_000) {
    final = await db.query.agentRuns.findFirst({ where: eq(agentRuns.id, runId) });
    if (final?.status === "completed" || final?.status === "failed") break;
    await new Promise(r => setTimeout(r, 2000));
  }
  console.log("Final status:", final?.status, final?.errorSummary ?? "");

  const items = await db.query.threadItems.findMany({
    where: eq(threadItems_table.threadId, threadId),
    orderBy: (t, { asc }) => [asc(t.sequence)],
  } as any);

  console.log(`thread_items count: ${items.length}`);
  for (const it of items) {
    const text = (it.contentJson as any)?.text ?? (it.contentJson as any)?.content?.[0]?.text ?? "(no text)";
    console.log(`  seq=${it.sequence} type=${it.itemType} role=${it.role} text=${text.slice(0, 80)}`);
  }
  if (final?.status === "completed") {
    await db.delete(workspaces).where(eq(workspaces.id, workspaceId));
    await db.delete(user).where(eq(user.id, ownerId));
    console.log("cleanup ok");
  } else {
    console.log("FAILED — leaving rows for debugging:");
    console.log("  workspace:", workspaceId);
    console.log("  thread:", threadId);
    console.log("  run:", runId);
    console.log("  owner:", ownerId);
  }
  process.exit(final?.status === "completed" ? 0 : 1);
}

import { threadItems as threadItems_table } from "../src/server/db/schema";
main().catch((e) => { console.error(e); process.exit(2); });
