<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { Eye, EyeOff } from '@lucide/vue';
import { useApiRequest, useHandleApiResponse } from '@/composables/useApi';
import { useAuthStore, type UserPayload } from '@/stores/auth';

const router = useRouter();
const authStore = useAuthStore();
const username = ref('');
const password = ref('');
const errorMessage = ref('');
const isSubmitting = ref(false);
const isPasswordVisible = ref(false);

const submit = async () => {
    errorMessage.value = '';
    isSubmitting.value = true;

    try {
        const response = await useApiRequest<UserPayload>(`/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username.value, password: password.value }),
            noRefresh: true,
        });
        const data = useHandleApiResponse(response);
        authStore.setAuthenticated(data);
        await router.push({ name: 'home' });
    } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : 'Unable to log in.';
    } finally {
        isSubmitting.value = false;
    }
};
</script>

<template>
    <main class="flex min-h-screen items-center justify-center bg-slate-100 px-4">
        <form class="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl" @submit.prevent="submit">
            <div class="mb-8 text-center">
                <h1 class="text-3xl font-semibold text-slate-900">Login</h1>
            </div>

            <div class="space-y-5">
                <label class="block text-sm font-medium text-slate-700">
                    Username
                    <input v-model="username" required autocomplete="username"
                        class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" />
                </label>
                <label class="block text-sm font-medium text-slate-700">
                    Password
                    <span class="relative mt-2 block">
                        <input v-model="password" required :type="isPasswordVisible ? 'text' : 'password'"
                            autocomplete="current-password"
                            class="w-full rounded-lg border border-slate-300 px-3 py-2.5 pr-11 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" />
                        <button type="button"
                            class="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-slate-400 hover:text-slate-700"
                            :aria-label="isPasswordVisible ? 'Hide password' : 'Show password'"
                            :title="isPasswordVisible ? 'Hide password' : 'Show password'"
                            @click="isPasswordVisible = !isPasswordVisible">
                            <EyeOff v-if="isPasswordVisible" class="h-5 w-5" aria-hidden="true" />
                            <Eye v-else class="h-5 w-5" aria-hidden="true" />
                        </button>
                    </span>
                </label>
            </div>

            <p v-if="errorMessage" class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">
                {{ errorMessage }}
            </p>
            <button type="submit" :disabled="isSubmitting"
                class="mt-6 w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60">
                {{ isSubmitting ? 'Logging in...' : 'Submit' }}
            </button>
        </form>
    </main>
</template>