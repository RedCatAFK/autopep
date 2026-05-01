import { TRPCError } from "@trpc/server";
import { z } from "zod";

import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { cancelRunForUser, createRunForPrompt } from "@/server/run-service";

export const runRouter = createTRPCRouter({
	cancel: protectedProcedure
		.input(z.object({ runId: z.string().uuid() }))
		.mutation(async ({ ctx, input }) => {
			return cancelRunForUser({
				db: ctx.db,
				userId: ctx.session.user.id,
				runId: input.runId,
			});
		}),
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
});
