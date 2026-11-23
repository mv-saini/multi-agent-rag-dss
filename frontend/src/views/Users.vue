<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
    ArrowLeft,
    Plus,
    Pencil,
    KeyRound,
    Trash2,
    X,
    RotateCw,
    Search,
} from '@lucide/vue';

import {
    useApiRequest,
    useHandleApiResponse,
} from '@/composables/useApi';

import DialogBox from '@/components/DialogBox.vue';

interface User {
    id: number;
    username: string;
    email: string;
    active: boolean;
    reset: boolean;
    role: number;
}

interface RoleOption {
    id: number;
    name: string;
}

interface UserForm {
    username: string;
    email: string;
    active: boolean;
    reset: boolean;
    role: number;
}

type Feedback = {
    type: 'success' | 'error';
    message: string;
};

type PendingAction = 'delete' | 'reset' | null;

const router = useRouter();

const users = ref<User[]>([]);
const roles = ref<RoleOption[]>([]);
const loading = ref(false);
const search = ref('');
const tableError = ref('');
const formError = ref<Feedback | null>(null);
const confirmationError = ref<Feedback | null>(null);

function clearTableError() {
    tableError.value = '';
}

function clearFormError() {
    formError.value = null;
}

function clearConfirmationError() {
    confirmationError.value = null;
}

const showForm = ref(false);
const editingUser = ref<User | null>(null);
const saving = ref(false);

const pendingAction = ref<PendingAction>(null);
const selectedUser = ref<User | null>(null);
const deletingUserId = ref<number | null>(null);
const resettingUserId = ref<number | null>(null);

function emptyForm(): UserForm {
    return {
        username: '',
        email: '',
        active: true,
        reset: false,
        role: -1,
    };
}

const form = ref<UserForm>(emptyForm());

const filteredUsers = computed(() => {
    const query = search.value.trim().toLowerCase();

    if (!query) return users.value;

    return users.value.filter((user) =>
        `${user.username} ${user.email} ${user.id}`
            .toLowerCase()
            .includes(query),
    );
});

const actionLoading = computed(
    () => deletingUserId.value !== null ||
        resettingUserId.value !== null,
);

const confirmationOpen = computed(
    () => pendingAction.value !== null && selectedUser.value !== null,
);

const confirmationTitle = computed(() => {
    if (pendingAction.value === 'delete') return 'Delete user';
    if (pendingAction.value === 'reset') return 'Reset password';
    return '';
});

const confirmationDescription = computed(() => {
    if (!selectedUser.value) return '';

    if (pendingAction.value === 'delete') {
        return `Are you sure you want to delete ${selectedUser.value.username}? This action cannot be undone.`;
    }

    if (pendingAction.value === 'reset') {
        return `Are you sure you want to reset the password for ${selectedUser.value.username}?`;
    }

    return '';
});

const confirmationButtonText = computed(() =>
    pendingAction.value === 'delete' ? 'Delete' : 'Reset password',
);

const formSucceeded = computed(
    () => formError.value?.type === 'success',
);

const confirmationSucceeded = computed(
    () => confirmationError.value?.type === 'success',
);

function errorMessage(
    err: unknown,
    fallback: string,
): string {
    return err instanceof Error ? err.message : fallback;
}

async function loadUsers(): Promise<boolean> {
    loading.value = true;
    clearTableError();

    try {
        const response = await useApiRequest<User[]>('/api/users');
        users.value = useHandleApiResponse(response);
        return true;
    } catch (err: unknown) {
        tableError.value = errorMessage(err, 'Unable to load users.');
        return false;
    } finally {
        loading.value = false;
    }
}

async function loadRoles(): Promise<boolean> {
    try {
        const response = await useApiRequest<RoleOption[]>('/api/users/roles');
        roles.value = useHandleApiResponse(response);
        return true;
    } catch (err: unknown) {
        tableError.value = errorMessage(err, 'Unable to load role options.');
        return false;
    }
}

function openCreate() {
    if (saving.value || actionLoading.value) return;

    editingUser.value = null;
    form.value = emptyForm();
    clearFormError();
    showForm.value = true;
}

function openEdit(user: User) {
    if (saving.value || actionLoading.value) return;

    editingUser.value = user;
    form.value = {
        username: user.username,
        email: user.email,
        active: user.active,
        reset: user.reset,
        role: user.role,
    };

    clearFormError();
    showForm.value = true;
}

function closeForm() {
    if (saving.value) return;

    showForm.value = false;
    editingUser.value = null;
    form.value = emptyForm();
    clearFormError();
}

async function saveUser() {
    if (saving.value || actionLoading.value) return;

    saving.value = true;
    clearFormError();

    try {
        const user = editingUser.value;

        const response = user
            ? await useApiRequest<string>(`/api/users/${user.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(form.value),
            })
            : await useApiRequest<string>('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: form.value.username,
                    email: form.value.email,
                    role: form.value.role,
                }),
            });

        const data = useHandleApiResponse(response);

        formError.value = {
            type: 'success',
            message: data,
        };

        await loadUsers();
    } catch (err: unknown) {
        formError.value = {
            type: 'error',
            message: errorMessage(err, 'Unable to save user.'),
        };
    } finally {
        saving.value = false;
    }
}

function askForConfirmation(
    action: Exclude<PendingAction, null>,
    user: User,
) {
    if (saving.value || actionLoading.value) return;

    clearConfirmationError();
    selectedUser.value = user;
    pendingAction.value = action;
}

function closeConfirmation() {
    if (actionLoading.value) return;

    pendingAction.value = null;
    selectedUser.value = null;
    clearConfirmationError();
}

async function confirmAction() {
    const action = pendingAction.value;
    const user = selectedUser.value;

    if (!action || !user || actionLoading.value) return;

    if (action === 'delete') {
        await deleteUser(user);
    } else if (action === 'reset') {
        await resetPassword(user);
    }
}

async function resetPassword(user: User) {
    if (resettingUserId.value !== null || deletingUserId.value !== null) {
        return;
    }

    resettingUserId.value = user.id;
    clearConfirmationError();

    try {
        const response = await useApiRequest<string>(
            `/api/users/reset-password/user/${user.id}`,
            { method: 'PUT' },
        );

        const data = useHandleApiResponse(response);

        confirmationError.value = {
            type: 'success',
            message: data,
        };

        await loadUsers();
    } catch (err: unknown) {
        confirmationError.value = {
            type: 'error',
            message: errorMessage(
                err,
                'Unable to reset user password.',
            ),
        };
    } finally {
        resettingUserId.value = null;
    }
}

async function deleteUser(user: User) {
    if (deletingUserId.value !== null || resettingUserId.value !== null) {
        return;
    }

    deletingUserId.value = user.id;
    clearConfirmationError();

    try {
        const response = await useApiRequest<string>(
            `/api/users/${user.id}`,
            { method: 'DELETE' },
        );

        const data = useHandleApiResponse(response);

        confirmationError.value = {
            type: 'success',
            message: data,
        };

        await loadUsers();
    } catch (err: unknown) {
        confirmationError.value = {
            type: 'error',
            message: errorMessage(err, 'Unable to delete user.'),
        };
    } finally {
        deletingUserId.value = null;
    }
}

onMounted(() => {
    void Promise.all([loadUsers(), loadRoles()]);
});
</script>

<template>
    <div class="flex h-dvh min-h-0 flex-col overflow-hidden bg-white text-gray-900">
        <header class="flex h-16 shrink-0 items-center gap-4 border-b border-gray-200 px-5 sm:px-8">
            <button type="button" aria-label="Back to chat" title="Back to chat"
                class="flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-100 hover:text-gray-900"
                @click="router.push({ name: 'home' })">
                <ArrowLeft :size="19" />
            </button>

            <h1 class="text-lg font-semibold tracking-tight">Users</h1>
        </header>

        <main class="flex min-h-0 flex-1 flex-col overflow-hidden px-5 py-7 sm:px-8">
            <div class="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col">
                <!-- Toolbar -->
                <div class="mb-4 flex shrink-0 flex-wrap items-center justify-between gap-3">
                    <div class="flex w-full max-w-md items-center gap-2">
                        <div class="relative w-full max-w-md">
                            <Search :size="16"
                                class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />

                            <input v-model="search" type="search" aria-label="Search users"
                                placeholder="Search users..."
                                class="h-9 w-full rounded-md border border-gray-200 bg-white pl-9 pr-3 text-sm outline-none placeholder:text-gray-400 focus:border-gray-400 focus:ring-1 focus:ring-gray-200" />
                        </div>


                        <button type="button" :disabled="loading" title="Reload users" aria-label="Reload users"
                            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-gray-200 text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-50"
                            @click="loadUsers">
                            <RotateCw :size="16" :class="{ 'animate-spin': loading }" />
                        </button>

                        <p class="mt-3 shrink-0 text-xs text-gray-400">
                            {{ filteredUsers.length }}
                            {{ filteredUsers.length === 1 ? 'user' : 'users' }}
                        </p>
                    </div>

                    <button type="button" :disabled="saving || actionLoading"
                        class="inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-3 text-sm font-medium text-white transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
                        @click="openCreate">
                        <Plus :size="16" />
                        Add user
                    </button>
                </div>

                <!-- Scrollable table -->
                <div class="min-h-0 flex-1 overflow-auto rounded-lg border border-gray-200">
                    <table class="w-full min-w-[700px] border-collapse text-left text-sm">
                        <thead class="sticky top-0 z-10 bg-gray-50">
                            <tr class="border-b border-gray-200 text-xs font-medium text-gray-500">
                                <th class="whitespace-nowrap px-4 py-3 font-medium">Username</th>
                                <th class="whitespace-nowrap px-4 py-3 font-medium">Email</th>
                                <th class="whitespace-nowrap px-4 py-3 font-medium">Status</th>
                                <th class="whitespace-nowrap px-4 py-3 font-medium">Role</th>
                                <th class="whitespace-nowrap px-4 py-3 font-medium">Password</th>
                                <th class="whitespace-nowrap px-4 py-3 text-right font-medium">Actions</th>
                            </tr>
                        </thead>

                        <tbody class="divide-y divide-gray-100">
                            <tr v-if="loading && users.length === 0">
                                <td colspan="6" class="px-4 py-12 text-center text-gray-400">
                                    Loading users...
                                </td>
                            </tr>

                            <tr v-else-if="tableError && users.length === 0">
                                <td colspan="6" class="px-4 py-8 text-center">
                                    <p role="alert" class="mb-3 text-sm text-red-600">
                                        {{ tableError }}
                                    </p>

                                    <button type="button" :disabled="loading"
                                        class="inline-flex h-8 items-center gap-2 rounded-md border border-gray-200 px-3 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                                        @click="loadUsers">
                                        <RotateCw :size="14" :class="{ 'animate-spin': loading }" />
                                        Try again
                                    </button>
                                </td>
                            </tr>


                            <tr v-else-if="filteredUsers.length === 0">
                                <td colspan="6" class="px-4 py-12 text-center text-gray-400">
                                    {{ search ? 'No users match your search.' : 'No users found.' }}
                                </td>
                            </tr>

                            <tr v-for="user in filteredUsers" :key="user.id"
                                class="transition-colors hover:bg-gray-50/70 border-b border-gray-100 last:border-b-0">
                                <td class="whitespace-nowrap px-4 py-3.5 font-medium">
                                    {{ user.username }}
                                </td>

                                <td class="whitespace-nowrap px-4 py-3.5 text-gray-500">
                                    {{ user.email }}
                                </td>

                                <td class="whitespace-nowrap px-4 py-3.5">
                                    <span class="inline-flex items-center gap-1.5 text-xs text-gray-700">
                                        <span class="h-1.5 w-1.5 rounded-full"
                                            :class="user.active ? 'bg-green-500' : 'bg-gray-300'" />
                                        {{ user.active ? 'Active' : 'Inactive' }}
                                    </span>
                                </td>

                                <td class="whitespace-nowrap px-4 py-3.5 text-gray-500">
                                    {{roles.find((role) => role.id === user.role)?.name ?? 'Unknown'}}
                                </td>

                                <td class="whitespace-nowrap px-4 py-3.5">
                                    <span class="inline-flex items-center gap-1.5 text-xs text-gray-700">
                                        <span class="h-1.5 w-1.5 rounded-full"
                                            :class="user.reset ? 'bg-red-500' : 'bg-green-500'" />
                                        {{ user.reset ? 'Reset Required' : 'OK' }}
                                    </span>
                                </td>

                                <td class="whitespace-nowrap px-4 py-2.5">
                                    <div class="flex items-center justify-end gap-1">
                                        <button type="button" :disabled="saving || actionLoading"
                                            :title="`Edit ${user.username}`" :aria-label="`Edit ${user.username}`"
                                            class="flex h-8 w-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50"
                                            @click="openEdit(user)">
                                            <Pencil :size="15" />
                                        </button>

                                        <button type="button" :disabled="saving || actionLoading"
                                            :title="`Reset password for ${user.username}`"
                                            :aria-label="`Reset password for ${user.username}`"
                                            class="flex h-8 w-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50"
                                            @click="askForConfirmation('reset', user)">
                                            <RotateCw v-if="resettingUserId === user.id" :size="15"
                                                class="animate-spin" />
                                            <KeyRound v-else :size="15" />
                                        </button>

                                        <button type="button" :disabled="saving || actionLoading"
                                            :title="`Delete ${user.username}`" :aria-label="`Delete ${user.username}`"
                                            class="flex h-8 w-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50"
                                            @click="askForConfirmation('delete', user)">
                                            <Trash2 :size="15" />
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </main>

        <DialogBox :open="showForm" :title="editingUser ? 'Edit user' : 'Add user'" :loading="saving"
            :show-footer="true" @close="closeForm">
            <div v-if="formError" role="status" aria-live="polite" :class="[
                'mb-4 flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm',
                formError.type === 'success'
                    ? 'border-green-200 bg-green-50 text-green-700'
                    : 'border-red-200 bg-red-50 text-red-700',
            ]">
                <span>{{ formError.message }}</span>

                <button type="button" aria-label="Dismiss message" class="shrink-0 rounded p-0.5 hover:bg-black/5"
                    @click="clearFormError">
                    <X :size="16" />
                </button>
            </div>

            <form id="user-form" class="space-y-4" @submit.prevent="saveUser" max-width="lg">
                <div>
                    <label for="username" class="mb-1.5 block text-sm text-gray-600">
                        Username
                    </label>
                    <input id="username" v-model.trim="form.username" required :disabled="saving"
                        autocomplete="username"
                        class="h-10 w-full rounded-md border border-gray-200 px-3 text-sm outline-none focus:border-gray-400" />
                </div>

                <div>
                    <label for="role" class="mb-1.5 block text-sm text-gray-600">
                        Role
                    </label>
                    <select id="role" v-model.number="form.role" required :disabled="saving || !roles.length"
                        class="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm outline-none focus:border-gray-400 disabled:cursor-not-allowed disabled:bg-gray-50">
                        <option v-for="role in roles" :key="role.id" :value="role.id">
                            {{ role.name }}
                        </option>
                    </select>
                </div>

                <div>
                    <label for="email" class="mb-1.5 block text-sm text-gray-600">
                        Email
                    </label>
                    <input id="email" v-model.trim="form.email" type="email" required :disabled="saving"
                        autocomplete="email"
                        class="h-10 w-full rounded-md border border-gray-200 px-3 text-sm outline-none focus:border-gray-400" />
                </div>

                <template v-if="editingUser">
                    <label class="flex items-center gap-2 text-sm text-gray-600">
                        <input v-model="form.active" type="checkbox" :disabled="saving" />
                        Active
                    </label>

                    <label class="flex items-center gap-2 text-sm text-gray-600">
                        <input v-model="form.reset" type="checkbox" :disabled="saving" />
                        Require password reset
                    </label>
                </template>
            </form>

            <template #footer>
                <button type="button" :disabled="saving"
                    class="h-9 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                    @click="closeForm">
                    Close
                </button>

                <button type="submit" form="user-form" :disabled="saving || formSucceeded"
                    class="h-9 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50">
                    {{ saving ? 'Saving...' : formSucceeded ? 'Saved' : 'Save' }}
                </button>
            </template>
        </DialogBox>

        <DialogBox :open="confirmationOpen" :title="confirmationTitle" cancel-text="Close" :loading="actionLoading"
            @close="closeConfirmation" max-width="md">
            <div v-if="confirmationError" role="status" aria-live="polite" :class="[
                'mb-4 flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm',
                confirmationError.type === 'success'
                    ? 'border-green-200 bg-green-50 text-green-700'
                    : 'border-red-200 bg-red-50 text-red-700',
            ]">
                <span>{{ confirmationError.message }}</span>

                <button type="button" aria-label="Dismiss message" class="shrink-0 rounded p-0.5 hover:bg-black/5"
                    @click="clearConfirmationError">
                    <X :size="16" />
                </button>
            </div>

            <p class="text-sm text-gray-600">
                {{ confirmationDescription }}
            </p>

            <template #footer>
                <button type="button" :disabled="actionLoading"
                    class="h-9 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                    @click="closeConfirmation">
                    Close
                </button>

                <button type="button" :disabled="actionLoading || confirmationSucceeded" @click="confirmAction"
                    class="h-9 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50">
                    {{
                        actionLoading
                            ? 'Please wait...'
                            : confirmationSucceeded
                                ? 'Completed'
                                : confirmationButtonText
                    }}
                </button>
            </template>
        </DialogBox>
    </div>
</template>
