<script setup>
defineProps({ capped: Boolean, presetOnly: Boolean, legend: { type: String, default: '到期时间' } })
const model = defineModel({ required: true })
const presets = [
  ['30m', '30 分钟'], ['1h', '1 小时'], ['6h', '6 小时'], ['24h', '24 小时'],
  ['7d', '7 天'], ['14d', '14 天'], ['30d', '30 天'], ['90d', '90 天'],
  ['180d', '180 天'], ['365d', '365 天'], ['forever', '永久'],
]
</script>

<template>
  <fieldset class="expiry">
    <legend>{{ legend }}</legend>
    <div v-if="!presetOnly" class="radio-group">
      <label><input v-model="model.mode" type="radio" value="preset"> 预设时长</label>
      <label><input v-model="model.mode" type="radio" value="date"> 指定日期和时间</label>
    </div>
    <select v-if="model.mode === 'preset'" v-model="model.preset" aria-label="有效期" required>
      <option value="" disabled>请选择有效期</option>
      <option v-for="[value, label] in presets" :key="value" :value="value" :disabled="value === 'forever' && capped">{{ label }}</option>
    </select>
    <input v-else v-model="model.date" type="datetime-local" aria-label="本地到期时间" required>
    <small v-if="model.mode === 'date'">使用当前设备的时区。</small>
  </fieldset>
</template>
