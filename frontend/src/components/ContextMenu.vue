<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';
import { Pencil, Trash2 } from '@lucide/vue';

const props = defineProps<{
    open: boolean;
    x: number;
    y: number;
    threadTitle?: string;
}>();

const emit = defineEmits<{
    (event: 'rename'): void;
    (event: 'delete'): void;
    (event: 'close'): void;
}>();

const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && props.open) {
        emit('close');
    }
};

const closeOnWindowChange = () => {
    if (props.open) {
        emit('close');
    }
};

onMounted(() => {
    window.addEventListener('keydown', closeOnEscape);
    window.addEventListener('resize', closeOnWindowChange);
    window.addEventListener('scroll', closeOnWindowChange, true);
});

onBeforeUnmount(() => {
    window.removeEventListener('keydown', closeOnEscape);
    window.removeEventListener('resize', closeOnWindowChange);
    window.removeEventListener('scroll', closeOnWindowChange, true);
});
</script>

<template>
    <Teleport to="body">
        <div v-if="open" class="fixed inset-0 z-[9998]" aria-hidden="true" @pointerdown="emit('close')"
            @contextmenu.prevent="emit('close')" />

        <div v-if="open"
            class="fixed z-[9999] min-w-44 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl p-1 gap-1"
            :style="{ left: `${x}px`, top: `${y}px` }" role="menu"
            :aria-label="`Actions for ${threadTitle || 'conversation'}`" @pointerdown.stop @contextmenu.prevent.stop>
            <button type="button"
                class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 rounded-xl"
                role="menuitem" @click="emit('rename')">
                <Pencil class="h-4 w-4" aria-hidden="true" />
                Rename
            </button>

            <button type="button"
                class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 rounded-xl"
                role="menuitem" @click="emit('delete')">
                <Trash2 class="h-4 w-4" aria-hidden="true" />
                Delete
            </button>
        </div>
    </Teleport>
</template>
