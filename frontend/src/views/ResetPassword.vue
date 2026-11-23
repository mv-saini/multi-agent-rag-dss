<script setup lang="ts">
import { computed, ref } from 'vue';
import { HandledApiError, useApiRequest, useHandleApiResponse } from '@/composables/useApi';
import { useAuthStore } from '@/stores/auth';
import router from '@/router';
import { Eye, EyeOff } from '@lucide/vue';

const authStore = useAuthStore();

const pass = ref({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
});

const showPassword = ref({
    current: false,
    new: false,
    confirm: false,
});

const newPassword = ref<HTMLInputElement | null>(null);

const togglePasswordVisibility = (field: keyof typeof showPassword.value) => {
    showPassword.value[field] = !showPassword.value[field];
};

const errorMessage = ref('');
const isSubmitting = ref(false);

const resetPassword = async () => {
    try {
        if (pass.value.newPassword !== pass.value.confirmPassword) {
            newPassword.value?.focus();
            errorMessage.value = 'New password and confirm password do not match.';
            return;
        }
        isSubmitting.value = true;

        const response = await useApiRequest<string>(
            `/api/users/reset-password`,
            {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                noRefresh: true,
                body: JSON.stringify({
                    old_password: pass.value.currentPassword,
                    new_password: pass.value.newPassword,
                    confirm_password: pass.value.confirmPassword,
                }),
            },
        );

        useHandleApiResponse(response);
        authStore.logout();
        router.push({ name: 'login' });
    } catch (error) {
        if (error instanceof HandledApiError) {
            errorMessage.value = error.message || 'Unable to reset password.';
            return;
        }
        console.error('Error resetting password:', error);
        errorMessage.value = 'Unable to reset password.';
    }
    finally {
        isSubmitting.value = false;
    }
};
</script>

<template>
    <main class="flex min-h-screen items-center justify-center bg-slate-100 px-4">
        <form class="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl" @submit.prevent="resetPassword">
            <div class="mb-8 text-center">
                <h1 class="text-3xl font-semibold text-slate-900">Reset Password</h1>
            </div>

            <div class="space-y-5">
                <label class="block text-sm font-medium text-slate-700">
                    Current Password
                    <span class="relative mt-2 block">
                        <input v-model="pass.currentPassword" required
                            :type="showPassword.current ? 'text' : 'password'" autocomplete="current-password"
                            class="w-full rounded-lg border border-slate-300 px-3 py-2.5 pr-11 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                            placeholder="Current Password" />
                        <button type="button"
                            class="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-slate-400 hover:text-slate-700"
                            :aria-label="showPassword.current ? 'Hide password' : 'Show password'"
                            :title="showPassword.current ? 'Hide password' : 'Show password'"
                            @click="togglePasswordVisibility('current')">
                            <EyeOff v-if="showPassword.current" class="h-5 w-5" aria-hidden="true" />
                            <Eye v-else class="h-5 w-5" aria-hidden="true" />
                        </button>
                    </span>
                </label>

                <label class="block text-sm font-medium text-slate-700">
                    New Password
                    <span class="relative mt-2 block">
                        <input v-model="pass.newPassword" required :type="showPassword.new ? 'text' : 'password'"
                            autocomplete="new-password" ref="newPassword"
                            class="w-full rounded-lg border border-slate-300 px-3 py-2.5 pr-11 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                            placeholder="New Password" />
                        <button type="button"
                            class="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-slate-400 hover:text-slate-700"
                            :aria-label="showPassword.new ? 'Hide password' : 'Show password'"
                            :title="showPassword.new ? 'Hide password' : 'Show password'"
                            @click="togglePasswordVisibility('new')">
                            <EyeOff v-if="showPassword.new" class="h-5 w-5" aria-hidden="true" />
                            <Eye v-else class="h-5 w-5" aria-hidden="true" />
                        </button>
                    </span>
                </label>

                <label class="block text-sm font-medium text-slate-700">
                    Confirm New Password
                    <span class="relative mt-2 block">
                        <input v-model="pass.confirmPassword" required
                            :type="showPassword.confirm ? 'text' : 'password'" autocomplete="new-password"
                            class="w-full rounded-lg border border-slate-300 px-3 py-2.5 pr-11 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                            placeholder="Confirm New Password" />
                        <button type="button"
                            class="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-slate-400 hover:text-slate-700"
                            :aria-label="showPassword.confirm ? 'Hide password' : 'Show password'"
                            :title="showPassword.confirm ? 'Hide password' : 'Show password'"
                            @click="togglePasswordVisibility('confirm')">
                            <EyeOff v-if="showPassword.confirm" class="h-5 w-5" aria-hidden="true" />
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