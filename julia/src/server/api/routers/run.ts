import { TRPCError } from "@trpc/server";
import { and, asc, eq, gt } from "drizzle-orm";
import { z } from "zod";

import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { projects, runEvents, runs } from "@/server/db/schema";
import { createRunForPrompt } from "@/server/run-service";

export const runRouter = createTRPCRouter({
	sendMessage: protectedProcedure
		.input(
			z.object({
				projectId: z.string().uuid(),
				threadId: z.string().uuid().optional(),
				content: z.string().trim().min(1).optional(),
				message: z.string().trim().min(1).optional(),
				contextReferenceIds: z.array(z.string().uuid()).optional(),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			const content = input.content ?? input.message;
			if (!content) {
				throw new TRPCError({
					code: "BAD_REQUEST",
					message: "Message content is required",
				});
			}
			if (!input.threadId) {
				throw new TRPCError({
					code: "BAD_REQUEST",
					message: "Thread id is required",
				});
			}

			return createRunForPrompt({
				db: ctx.db,
				userId: ctx.session.user.id,
				projectId: input.projectId,
				threadId: input.threadId,
				content,
				contextReferenceIds: input.contextReferenceIds,
			});
		}),

	listEvents: protectedProcedure
		.input(
			z.object({
				runId: z.string().uuid(),
				afterSequence: z.number().int().min(0).optional(),
				after: z.number().int().min(0).optional(),
			}),
		)
		.query(async ({ ctx, input }) => {
			const [run] = await ctx.db
				.select({ id: runs.id })
				.from(runs)
				.innerJoin(projects, eq(projects.id, runs.projectId))
				.where(
					and(
						eq(runs.id, input.runId),
						eq(projects.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!run) {
				throw new TRPCError({ code: "NOT_FOUND", message: "Run not found" });
			}

			return ctx.db
				.select()
				.from(runEvents)
				.where(
					and(
						eq(runEvents.runId, input.runId),
						gt(runEvents.sequence, input.afterSequence ?? input.after ?? 0),
					),
				)
				.orderBy(asc(runEvents.sequence));
		}),
});
