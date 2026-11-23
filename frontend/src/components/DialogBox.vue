<script setup lang="ts">
import { X } from '@lucide/vue';
import { onBeforeUnmount, watch } from 'vue';

const props = withDefaults(defineProps<{
    open: boolean;
    title: string;
    cancelText?: string;
    loading?: boolean;
    showFooter?: boolean;
    closeOnOverlay?: boolean;
    maxWidth?: 'sm' | 'md' | 'lg' | 'xl';
}>(), {
    cancelText: 'Cancel',
    loading: false,
    showFooter: true,
    closeOnOverlay: true,
    maxWidth: 'md',
});

const emit = defineEmits<{
    close: [];
}>();

function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && !props.loading) {
        emit('close');
    }
}

watch(
    () => props.open,
    (isOpen) => {
        if (isOpen) {
            document.addEventListener('keydown', onKeydown);
        } else {
            document.removeEventListener('keydown', onKeydown);
        }
    },
    { immediate: true },
);

onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown);
});
</script>

<template>
    <Teleport to="body">
        <Transition enter-active-class="transition duration-150 ease-out" enter-from-class="opacity-0"
            enter-to-class="opacity-100" leave-active-class="transition duration-100 ease-in"
            leave-from-class="opacity-100" leave-to-class="opacity-0">
            <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/30 p-4"
                @click.self="closeOnOverlay && !loading && emit('close')">
                <section role="dialog" aria-modal="true" :aria-label="title" :class="[
                    'my-auto w-full rounded-xl border border-gray-200 bg-white shadow-xl',
                    {
                        'max-w-sm': props.maxWidth === 'sm',
                        'max-w-md': props.maxWidth === 'md',
                        'max-w-lg': props.maxWidth === 'lg',
                        'max-w-xl': props.maxWidth === 'xl',
                    },
                ]" @click.stop>
                    <header class="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
                        <div class="min-w-0">
                            <h2 class="text-base font-semibold text-gray-900">
                                {{ title }}
                            </h2>
                        </div>

                        <button type="button" aria-label="Close dialog" :disabled="loading"
                            class="shrink-0 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
                            @click="emit('close')">
                            <X :size="18" />
                        </button>
                    </header>

                    <div class="max-h-[70dvh] overflow-y-auto p-5">
                        <slot />
                    </div>

                    <footer v-if="showFooter" class="flex justify-end gap-2 border-t border-gray-100 px-5 py-4">
                        <slot name="footer">
                            <button type="button" :disabled="loading"
                                class="h-9 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                                @click="emit('close')">
                                {{ cancelText }}
                            </button>
                        </slot>
                    </footer>
                </section>
            </div>
        </Transition>
    </Teleport>
</template>
