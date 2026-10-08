<script setup lang="ts">
import { computed, ref } from 'vue';
import { ChevronDown, ChevronRight, Pencil, Plus, X } from '@lucide/vue';

defineOptions({ name: 'ProfileNodeEditor' });

type ProfileObject = Record<string, unknown>;
type ProfileScalar = string | number | boolean;

const props = withDefaults(defineProps<{
    label?: string;
    modelValue: unknown;
    removable?: boolean;
}>(), {
    label: '',
    removable: false,
});

const emit = defineEmits<{
    (event: 'update:modelValue', value: unknown): void;
    (event: 'remove'): void;
}>();

const isArray = computed(() => Array.isArray(props.modelValue));
const isObject = computed(() => (
    props.modelValue !== null
    && typeof props.modelValue === 'object'
    && !Array.isArray(props.modelValue)
));
const isContainer = computed(() => isArray.value || isObject.value);
const isExpanded = ref(!isContainer.value || props.label === 'Profile');

const objectEntries = computed(() => (
    isObject.value ? Object.entries(props.modelValue as ProfileObject) : []
));
const arrayItems = computed(() => (
    isArray.value ? props.modelValue as unknown[] : []
));

const valueType = computed<'text' | 'number' | 'boolean' | 'object' | 'array'>(() => {
    if (isArray.value) return 'array';
    if (isObject.value) return 'object';
    if (typeof props.modelValue === 'number') return 'number';
    if (typeof props.modelValue === 'boolean') return 'boolean';
    return 'text';
});

const updateScalar = (value: string, type: string) => {
    let nextValue: ProfileScalar = value;
    if (type === 'number') nextValue = Number(value);
    if (type === 'boolean') nextValue = value === 'true';
    emit('update:modelValue', nextValue);
};

const updateObjectValue = (key: string, value: unknown) => {
    emit('update:modelValue', {
        ...(props.modelValue as ProfileObject),
        [key]: value,
    });
};

const renameObjectKey = (oldKey: string, event: Event) => {
    const newKey = (event.target as HTMLInputElement).value.trim();
    if (!newKey || newKey === oldKey) return;

    const current = props.modelValue as ProfileObject;
    if (Object.keys(current).some(key => key === newKey)) return;

    const renamed: ProfileObject = {};
    Object.entries(current).forEach(([key, value]) => {
        renamed[key === oldKey ? newKey : key] = value;
    });
    emit('update:modelValue', renamed);
};

const removeObjectKey = (keyToRemove: string) => {
    const nextValue = { ...(props.modelValue as ProfileObject) };
    delete nextValue[keyToRemove];
    emit('update:modelValue', nextValue);
};

const addObjectProperty = () => {
    const current = props.modelValue as ProfileObject;
    let key = 'new_field';
    let suffix = 2;
    while (key in current) key = `new_field_${suffix++}`;
    emit('update:modelValue', { ...current, [key]: '' });
};

const updateArrayItem = (index: number, value: unknown) => {
    const nextValue = [...(props.modelValue as unknown[])];
    nextValue[index] = value;
    emit('update:modelValue', nextValue);
};

const removeArrayItem = (index: number) => {
    emit('update:modelValue', (props.modelValue as unknown[]).filter((_, itemIndex) => itemIndex !== index));
};

const addArrayItem = () => {
    emit('update:modelValue', [...(props.modelValue as unknown[]), '']);
};

const changeValueType = (event: Event) => {
    const type = (event.target as HTMLSelectElement).value;
    if (type === 'object') emit('update:modelValue', {});
    else if (type === 'array') emit('update:modelValue', []);
    else updateScalar('', type);
};
</script>

<template>
    <section :class="isContainer ? 'rounded-xl border border-gray-200 bg-white p-3 sm:p-4' : ''">
        <div v-if="isContainer" class="flex items-center gap-2">
            <button type="button" class="flex min-w-0 flex-1 items-center gap-2 text-left"
                @click="isExpanded = !isExpanded">
                <span class="text-sm font-semibold text-gray-800">{{ label || (isArray ? 'List' : 'Group') }}</span>
                <span v-if="isArray"
                    class="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">{{
                        arrayItems.length }} items</span>
                <span v-else class="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">{{
                    objectEntries.length }} properties</span>
                <ChevronDown v-if="isExpanded" class="ml-auto h-4 w-4 text-gray-400" aria-hidden="true" />
                <ChevronRight v-else class="ml-auto h-4 w-4 text-gray-400" aria-hidden="true" />
            </button>
            <button v-if="removable" type="button" aria-label="Remove item"
                class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-lg leading-none text-gray-400 hover:bg-red-50 hover:text-red-600"
                @click="emit('remove')">
                <X class="h-4 w-4" aria-hidden="true" />
            </button>
        </div>

        <div v-if="isObject && isExpanded" class="mt-3 space-y-2">
            <div v-for="([key, value]) in objectEntries" :key="key"
                class="rounded-lg border border-gray-100 bg-gray-50/70 p-2">
                <div class="mb-2 flex items-center gap-2">
                    <input :value="key" aria-label="Property name"
                        class="min-w-0 flex-1 bg-transparent px-1.5 py-1 border border-gray-200 rounded-md text-sm font-medium bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                        @change="renameObjectKey(key, $event)" />
                    <button type="button" aria-label="Remove property"
                        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-lg leading-none text-gray-400 hover:bg-red-50 hover:text-red-600"
                        @click="removeObjectKey(key)">
                        <X class="h-4 w-4" aria-hidden="true" />
                    </button>
                </div>
                <ProfileNodeEditor :model-value="value"
                    :label="typeof value === 'object' && value !== null ? '' : undefined" :removable="false"
                    @update:model-value="updateObjectValue(key, $event)" />
            </div>
            <button type="button"
                class="rounded-lg border border-dashed border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 hover:border-blue-400 hover:text-blue-600"
                @click="addObjectProperty">
                <Plus class="mr-1 inline-block h-4 w-4" aria-hidden="true" />Add property
            </button>
        </div>

        <div v-else-if="isArray && isExpanded" class="mt-3 space-y-2">
            <div v-if="!arrayItems.length"
                class="rounded-lg border border-dashed border-gray-300 px-3 py-3 text-sm text-gray-500">This list is
                empty.</div>
            <div v-for="(item, index) in arrayItems" :key="index" class="flex items-start gap-2">
                <span class="mt-2 w-6 shrink-0 text-xs font-medium text-gray-400">{{ index + 1 }}</span>
                <ProfileNodeEditor class="min-w-0 flex-1" :model-value="item" :label="''" :removable="true"
                    @update:model-value="updateArrayItem(index, $event)" @remove="removeArrayItem(index)" />
            </div>
            <button type="button"
                class="rounded-lg border border-dashed border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 hover:border-blue-400 hover:text-blue-600"
                @click="addArrayItem">
                <Plus class="mr-1 inline-block h-4 w-4" aria-hidden="true" />Add item
            </button>
        </div>

        <div v-else-if="!isContainer" class="flex flex-col gap-2 sm:flex-row">
            <input v-if="valueType === 'text'" :value="String(modelValue ?? '')" aria-label="Value"
                placeholder="Enter a value"
                class="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @input="updateScalar(($event.target as HTMLInputElement).value, 'text')" />
            <input v-else-if="valueType === 'number'" :value="String(modelValue)" type="number" aria-label="Value"
                class="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @input="updateScalar(($event.target as HTMLInputElement).value, 'number')" />
            <select v-else :value="String(modelValue)" aria-label="Value"
                class="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @change="updateScalar(($event.target as HTMLSelectElement).value, 'boolean')">
                <option value="true">True</option>
                <option value="false">False</option>
            </select>
            <select :value="valueType" aria-label="Value type"
                class="rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @change="changeValueType">
                <option value="text">Text</option>
                <option value="number">Number</option>
                <option value="boolean">True / false</option>
                <option value="object">Group</option>
                <option value="array">List</option>
            </select>
        </div>
    </section>
</template>