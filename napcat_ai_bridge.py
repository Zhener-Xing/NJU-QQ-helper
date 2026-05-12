* {
  box-sizing: border-box;
}

:root {
  --bg: #0f1116;
  --panel: #181b22;
  --panel-soft: #1d2129;
  --line: rgba(255, 255, 255, 0.1);
  --text: #e7eaf0;
  --muted: #adb4c0;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC",
    "Microsoft YaHei", sans-serif;
  background: linear-gradient(180deg, #14171d, var(--bg));
  color: var(--text);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
}

.page-header {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 18px 16px 14px;
  background: rgba(15, 17, 22, 0.95);
  color: #f3f4f6;
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
  width: min(100%, 430px);
}

.page-header h1 {
  margin: 0 0 8px;
  font-size: 22px;
  letter-spacing: 0.01em;
  font-weight: 650;
}

.page-header p {
  margin: 0;
  opacity: 0.78;
  color: #c3c7d0;
}

.container {
  width: min(100%, 430px);
  margin: 0;
  padding: 14px 14px 26px;
  display: grid;
  gap: 12px;
}

.panel {
  background: linear-gradient(180deg, var(--panel-soft), var(--panel));
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

h2 {
  margin-top: 0;
  margin-bottom: 6px;
  color: #eef1f6;
  font-weight: 620;
  letter-spacing: 0.01em;
  font-size: 17px;
}

.hint {
  color: #a8aeb9;
  margin: 0 0 4px;
  font-size: 13px;
}

form {
  display: grid;
  gap: 12px;
}

label {
  display: block;
  font-weight: 560;
  color: #cfd4dd;
  margin-bottom: 6px;
  font-size: 13px;
}

textarea,
input,
select {
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 10px;
  padding: 11px 12px;
  font-size: 14px;
  background: rgba(18, 20, 26, 0.65);
  color: #e9ecf2;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease;
}

textarea::placeholder,
input::placeholder {
  color: #8f96a4;
}

textarea:focus,
input:focus,
select:focus {
  outline: none;
  border-color: rgba(214, 219, 228, 0.65);
  box-shadow: 0 0 0 3px rgba(214, 219, 228, 0.12);
  background: rgba(16, 18, 24, 0.85);
}

button {
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: linear-gradient(180deg, #d3d7df, #a8aeb9);
  color: #171a1f;
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.14s ease, filter 0.2s ease, box-shadow 0.2s ease;
}

button:hover {
  filter: brightness(1.02);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25);
}

button.secondary {
  background: linear-gradient(180deg, #bbc1cc, #9098a6);
  border-color: rgba(255, 255, 255, 0.2);
  color: #171a1f;
}

button.danger {
  background: linear-gradient(180deg, #8b909a, #6f7682);
  border-color: rgba(255, 255, 255, 0.16);
  color: #f1f3f7;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.toolbar {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 12px;
}

.toolbar-actions {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

.toolbar-actions select {
  min-width: 0;
}

.activity-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  gap: 10px;
}

.activity-item {
  border: 1px solid rgba(255, 255, 255, 0.13);
  border-radius: 12px;
  padding: 12px;
  display: grid;
  gap: 10px;
  background: linear-gradient(180deg, rgba(22, 25, 31, 0.9), rgba(17, 20, 26, 0.9));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.item-title {
  margin: 0 0 6px;
  font-weight: 700;
  color: #f0f3f8;
}

.item-meta {
  margin: 0;
  color: #acb3bf;
  font-size: 13px;
  line-height: 1.6;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.item-meta .meta-line {
  margin: 0;
  word-break: break-word;
}

.item-meta a {
  color: #8ab4f8;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.item-meta a:hover {
  color: #b8d2ff;
}

.item-actions {
  display: flex;
  gap: 8px;
}

.item-actions button {
  flex: 1;
}

button.favorite-btn.favorite-on {
  background: linear-gradient(180deg, #d4a84b, #b8892e);
  border-color: rgba(255, 255, 255, 0.22);
  color: #1a1410;
  font-weight: 600;
}

.activity-item-deleted {
  opacity: 0.6;
  border-style: dashed;
}

.empty-state {
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}
