<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <div class="not-found__card">
      <h1 class="not-found__title">页面不存在</h1>
      <p class="not-found__desc">地址有误或页面尚未提供，回到聊天页继续。</p>
      <button class="not-found__btn" type="button" @click="router.push('/chat')">
        返回聊天
      </button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.not-found {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;

  &__card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 32px 40px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }

  &__title {
    font-size: 22px;
    font-weight: 650;
  }

  &__desc {
    font-size: 14px;
    color: var(--text-secondary);
  }

  &__btn {
    margin-top: 8px;
    height: 30px;
    padding: 0 16px;
    border: none;
    border-radius: 6px;
    background: var(--accent); // 主按钮
    color: var(--text-inverse);
    font-size: 13.5px;
    cursor: pointer;

    &:hover {
      background: var(--accent-hover);
    }
  }
}
</style>
