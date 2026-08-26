import type { QueryKey, UseMutationOptions, UseMutationResult, UseQueryOptions, UseQueryResult } from '@tanstack/react-query';
import type { EditInput, EditResult, HealthStatus, LabConfig, ReviewCancellationInput, ReviewDecisionInput } from './api.schemas';
import { customFetch } from '../custom-fetch';
import type { ErrorType, BodyType } from '../custom-fetch';
type AwaitedInput<T> = PromiseLike<T> | T;
type Awaited<O> = O extends AwaitedInput<infer T> ? T : never;
type SecondParameter<T extends (...args: never) => unknown> = Parameters<T>[1];
export declare const getHealthCheckUrl: () => string;
/**
 * @summary Health check
 */
export declare const healthCheck: (options?: Parameters<typeof customFetch>[1]) => Promise<HealthStatus>;
export declare const getHealthCheckQueryKey: () => readonly ["/api/healthz"];
export declare const getHealthCheckQueryOptions: <TData = Awaited<ReturnType<typeof healthCheck>>, TError = ErrorType<unknown>>(options?: {
    query?: UseQueryOptions<Awaited<ReturnType<typeof healthCheck>>, TError, TData>;
    request?: SecondParameter<typeof customFetch>;
}) => UseQueryOptions<Awaited<ReturnType<typeof healthCheck>>, TError, TData> & {
    queryKey: QueryKey;
};
export type HealthCheckQueryResult = NonNullable<Awaited<ReturnType<typeof healthCheck>>>;
export type HealthCheckQueryError = ErrorType<unknown>;
/**
 * @summary Health check
 */
export declare function useHealthCheck<TData = Awaited<ReturnType<typeof healthCheck>>, TError = ErrorType<unknown>>(options?: {
    query?: UseQueryOptions<Awaited<ReturnType<typeof healthCheck>>, TError, TData>;
    request?: SecondParameter<typeof customFetch>;
}): UseQueryResult<TData, TError> & {
    queryKey: QueryKey;
};
export declare const getGetLabConfigUrl: () => string;
/**
 * @summary Get safe engine configuration state
 */
export declare const getLabConfig: (options?: Parameters<typeof customFetch>[1]) => Promise<LabConfig>;
export declare const getGetLabConfigQueryKey: () => readonly ["/api/lab/config"];
export declare const getGetLabConfigQueryOptions: <TData = Awaited<ReturnType<typeof getLabConfig>>, TError = ErrorType<unknown>>(options?: {
    query?: UseQueryOptions<Awaited<ReturnType<typeof getLabConfig>>, TError, TData>;
    request?: SecondParameter<typeof customFetch>;
}) => UseQueryOptions<Awaited<ReturnType<typeof getLabConfig>>, TError, TData> & {
    queryKey: QueryKey;
};
export type GetLabConfigQueryResult = NonNullable<Awaited<ReturnType<typeof getLabConfig>>>;
export type GetLabConfigQueryError = ErrorType<unknown>;
/**
 * @summary Get safe engine configuration state
 */
export declare function useGetLabConfig<TData = Awaited<ReturnType<typeof getLabConfig>>, TError = ErrorType<unknown>>(options?: {
    query?: UseQueryOptions<Awaited<ReturnType<typeof getLabConfig>>, TError, TData>;
    request?: SecondParameter<typeof customFetch>;
}): UseQueryResult<TData, TError> & {
    queryKey: QueryKey;
};
export declare const getGenerateEditUrl: () => string;
/**
 * @summary Generate an un-applied editing proposal
 */
export declare const generateEdit: (editInput: EditInput, options?: Parameters<typeof customFetch>[1]) => Promise<EditResult>;
export declare const getGenerateEditMutationOptions: <TError = ErrorType<void>, TContext = unknown>(options?: {
    mutation?: UseMutationOptions<Awaited<ReturnType<typeof generateEdit>>, TError, {
        data: BodyType<EditInput>;
    }, TContext>;
    request?: SecondParameter<typeof customFetch>;
}) => UseMutationOptions<Awaited<ReturnType<typeof generateEdit>>, TError, {
    data: BodyType<EditInput>;
}, TContext>;
export type GenerateEditMutationResult = NonNullable<Awaited<ReturnType<typeof generateEdit>>>;
export type GenerateEditMutationBody = BodyType<EditInput>;
export type GenerateEditMutationError = ErrorType<void>;
/**
* @summary Generate an un-applied editing proposal
*/
export declare const useGenerateEdit: <TError = ErrorType<void>, TContext = unknown>(options?: {
    mutation?: UseMutationOptions<Awaited<ReturnType<typeof generateEdit>>, TError, {
        data: BodyType<EditInput>;
    }, TContext>;
    request?: SecondParameter<typeof customFetch>;
}) => UseMutationResult<Awaited<ReturnType<typeof generateEdit>>, TError, {
    data: BodyType<EditInput>;
}, TContext>;
export declare const getDecideReviewUrl: () => string;
/**
 * @summary Send an explicit decision for a pending hosted review batch
 */
export declare const decideReview: (reviewDecisionInput: ReviewDecisionInput, options?: Parameters<typeof customFetch>[1]) => Promise<EditResult>;
export declare const getDecideReviewMutationOptions: <TError = ErrorType<void>, TContext = unknown>(options?: {
    mutation?: UseMutationOptions<Awaited<ReturnType<typeof decideReview>>, TError, {
        data: BodyType<ReviewDecisionInput>;
    }, TContext>;
    request?: SecondParameter<typeof customFetch>;
}) => UseMutationOptions<Awaited<ReturnType<typeof decideReview>>, TError, {
    data: BodyType<ReviewDecisionInput>;
}, TContext>;
export type DecideReviewMutationResult = NonNullable<Awaited<ReturnType<typeof decideReview>>>;
export type DecideReviewMutationBody = BodyType<ReviewDecisionInput>;
export type DecideReviewMutationError = ErrorType<void>;
/**
* @summary Send an explicit decision for a pending hosted review batch
*/
export declare const useDecideReview: <TError = ErrorType<void>, TContext = unknown>(options?: {
    mutation?: UseMutationOptions<Awaited<ReturnType<typeof decideReview>>, TError, {
        data: BodyType<ReviewDecisionInput>;
    }, TContext>;
    request?: SecondParameter<typeof customFetch>;
}) => UseMutationResult<Awaited<ReturnType<typeof decideReview>>, TError, {
    data: BodyType<ReviewDecisionInput>;
}, TContext>;
export declare const getCancelReviewUrl: () => string;
/**
 * @summary Cancel a pending hosted review job
 */
export declare const cancelReview: (reviewCancellationInput: ReviewCancellationInput, options?: Parameters<typeof customFetch>[1]) => Promise<EditResult>;
export declare const getCancelReviewMutationOptions: <TError = ErrorType<void>, TContext = unknown>(options?: {
    mutation?: UseMutationOptions<Awaited<ReturnType<typeof cancelReview>>, TError, {
        data: BodyType<ReviewCancellationInput>;
    }, TContext>;
    request?: SecondParameter<typeof customFetch>;
}) => UseMutationOptions<Awaited<ReturnType<typeof cancelReview>>, TError, {
    data: BodyType<ReviewCancellationInput>;
}, TContext>;
export type CancelReviewMutationResult = NonNullable<Awaited<ReturnType<typeof cancelReview>>>;
export type CancelReviewMutationBody = BodyType<ReviewCancellationInput>;
export type CancelReviewMutationError = ErrorType<void>;
/**
* @summary Cancel a pending hosted review job
*/
export declare const useCancelReview: <TError = ErrorType<void>, TContext = unknown>(options?: {
    mutation?: UseMutationOptions<Awaited<ReturnType<typeof cancelReview>>, TError, {
        data: BodyType<ReviewCancellationInput>;
    }, TContext>;
    request?: SecondParameter<typeof customFetch>;
}) => UseMutationResult<Awaited<ReturnType<typeof cancelReview>>, TError, {
    data: BodyType<ReviewCancellationInput>;
}, TContext>;
export {};
//# sourceMappingURL=api.d.ts.map