import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useApiRequest } from '@/composables/useApi';
import router from '@/router';

export interface UserPayload {
    id: number;
    username: string;
    email: string;
    active: boolean;
    reset: boolean;
    role: number;
}

export const useAuthStore = defineStore('authentication', () => {
    const user = ref<UserPayload | null>(null);
    const loggedOut = ref(false);
    const isAuthenticated = computed(() => !!user.value);
    const isAdmin = computed(() => user.value?.role === 1);
    const requireReset = computed(() => !!user.value && user.value.reset);
    const refreshInProgress = ref(false);

    function setAuthenticated(userData: UserPayload) {
        user.value = userData;
        loggedOut.value = false;
    }

    async function logout() {
        user.value = null;
        loggedOut.value = true;
        refreshInProgress.value = false;
        await useApiRequest('/api/auth/logout', {
            method: 'POST',
            credentials: 'include',
            noRefresh: true,
        });

        router.push({ name: 'login' });
    }

    async function refreshToken(): Promise<boolean> {
        if (refreshInProgress.value) {
            return new Promise((resolve) => {
                const interval = setInterval(() => {
                    if (!refreshInProgress.value) {
                        clearInterval(interval);
                        resolve(isAuthenticated.value);
                    }
                }, 100);
            });
        }

        refreshInProgress.value = true;

        const { error } = await useApiRequest('/api/auth/refresh', {
            method: 'POST',
            credentials: 'include',
            noRefresh: true,
        });

        if (error) {
            logout();
            return false;
        }

        refreshInProgress.value = false;
        return true;
    }

    async function checkAuthStatus() {
        if (loggedOut.value) return;
        const { data, error } = await useApiRequest<UserPayload>('/api/auth/me');
        if (!error && data) {
            user.value = data;
        } else {
            user.value = null;
        }
    }

    return {
        user,
        loggedOut,
        isAuthenticated,
        isAdmin,
        requireReset,
        setAuthenticated,
        logout,
        refreshToken,
        checkAuthStatus,
    };
});
