import { useAuthStore } from '@/stores/auth';

export class HandledApiError extends Error {
    constructor(message: string) {
        super(message);
        this.name = 'HandledApiError';
    }
}

type ApiOptions = RequestInit & { noRefresh?: boolean; blob?: boolean };
type ApiResponse<T> = { data: T | null; error?: string };

export async function useApiRequest<T = unknown>(
    url: string,
    options: ApiOptions = {},
): Promise<ApiResponse<T>> {
    const makeRequest = async (
        isRetry = false,
    ): Promise<{ data: T | null; error?: string }> => {
        try {
            const { noRefresh, ...fetchOptions } = options;

            const requestOptions: RequestInit = {
                ...fetchOptions,
                credentials: options.credentials || 'include',
            };

            const response = await fetch(url, requestOptions);

            if (response.status === 401 && !isRetry && !noRefresh) {
                const authStore = useAuthStore();
                const refreshSuccess = await authStore.refreshToken();
                if (refreshSuccess) {
                    return makeRequest(true);
                } else {
                    return { data: null, error: 'Session expired. Please log in again.' };
                }
            }

            const blob = options.blob && isBlob(response);
            const responseData = blob ? await response.blob() : await response.json()
            
            if (!response.ok) {
                return {
                    data: null,
                    error: responseData.error || `Network or server error`,
                };
            }

            return {
                data: blob ? responseData : responseData.data,
                error: responseData.error,
            };
        } catch (error) {
            if (options.signal?.aborted) throw error;
            console.error(error);
            return { data: null, error: 'Network or server error' };
        }
    };

    return makeRequest();
}

export async function useApiStream(
    url: string,
    options: RequestInit = {},
    isRetry = false,
): Promise<Response> {
    const response = await fetch(url, {
        ...options,
        credentials: options.credentials || 'include',
    });

    if (response.status === 401 && !isRetry) {
        const authStore = useAuthStore();
        const refreshSuccess = await authStore.refreshToken();
        if (refreshSuccess) {
            return useApiStream(url, options, true);
        }
        await authStore.logout();
    }

    return response;
}

function isBlob(response: Response): boolean {
    return !response.headers.get('Content-Type')?.includes('application/json');
}

export const useHandleApiResponse = <T>(response: ApiResponse<T>): T => {
    const { data, error } = response;
    if (error) throw new HandledApiError(error);
    if (data === null || data === undefined) {
        throw new HandledApiError('Missing data in API response');
    }
    return data;
};
