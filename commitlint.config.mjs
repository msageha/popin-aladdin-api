/** @type {import('@commitlint/types').UserConfig} */
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    // 日本語の件名に英語の固有名詞 (Renovate, GitHub など) が先頭に来ると
    // sentence-case / upper-case 判定で誤爆するため、大文字小文字の検査は行わない
    "subject-case": [0],
  },
};
