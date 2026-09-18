<template>
  <div v-if="reviews.length" class="review-block">
    <div class="review-header" @click="collapsed = !collapsed">
      <span class="review-icon">{{ allPassed ? '✅' : '🔄' }}</span>
      <span class="review-label">
        质量评审（{{ reviews.length }} 轮{{ allPassed ? '通过' : '' }}）
      </span>
      <span class="chevron" :class="{ open: !collapsed }">▸</span>
    </div>

    <transition name="fade">
      <div v-if="!collapsed" class="review-body">
        <div
          v-for="(review, i) in reviews"
          :key="i"
          class="review-round"
        >
          <div class="round-header">
            <span class="round-badge" :class="review.verdict">
              {{ review.verdict === 'pass' ? '✓ 通过' : '✗ 修正' }}
            </span>
            <span class="round-label">第 {{ review.round }} 轮</span>
          </div>
          <div v-if="review.feedback" class="round-feedback">
            {{ review.feedback }}
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  reviews: { type: Array, default: () => [] },  // [{round, verdict, feedback}]
})

const collapsed = ref(true)

const allPassed = computed(() =>
  props.reviews.length > 0 &&
  props.reviews[props.reviews.length - 1]?.verdict === 'pass'
)
</script>

<style scoped>
.review-block {
  margin: 8px 0;
  border-radius: 10px;
  background: #f5faf5;
  border: 1px solid #d4edda;
  overflow: hidden;
  font-size: 0.85rem;
}

.review-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}

.review-header:hover { background: #ecf5ec; }

.review-icon { font-size: 1rem; }

.review-label {
  font-weight: 500;
  color: #2d6a4f;
  flex: 1;
}

.chevron {
  font-size: 0.9rem;
  color: #6aab8e;
  transition: transform 0.2s;
}

.chevron.open { transform: rotate(90deg); }

.review-body {
  border-top: 1px solid #d4edda;
  padding: 10px 14px;
}

.review-round {
  padding: 6px 0;
}

.review-round:not(:last-child) {
  border-bottom: 1px solid #e8f5e8;
}

.round-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.round-badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
}

.round-badge.pass {
  background: #d4edda;
  color: #1a7f37;
}

.round-badge.revise {
  background: #fff3cd;
  color: #856404;
}

.round-label {
  color: #555;
  font-size: 0.8rem;
}

.round-feedback {
  color: #666;
  font-size: 0.8rem;
  padding-left: 4px;
  line-height: 1.5;
}

.fade-enter-active,
.fade-leave-active { transition: all 0.2s ease; overflow: hidden; }
.fade-enter-from,
.fade-leave-to { opacity: 0; max-height: 0; }
.fade-enter-to,
.fade-leave-from { opacity: 1; max-height: 500px; }
</style>
