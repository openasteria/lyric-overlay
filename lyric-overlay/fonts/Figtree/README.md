# Шрифт Figtree

По макету Figma виджет использует **Figtree** (14px). Шрифт распространяется по
лицензии SIL Open Font License и бесплатно доступен:

- Google Fonts: https://fonts.google.com/specimen/Figtree
- GitHub: https://github.com/madigraphikhq/figma — нет; официальный источник:
  https://fonts.google.com/download?family=Figtree

## Установка

```bash
mkdir -p ~/.local/share/fonts/Figtree
unzip Figtree.zip -d ~/.local/share/fonts/Figtree/
fc-cache -f
fc-list | grep -i figtree   # проверка
```

Положите `.ttf` файлы и в `fonts/Figtree/` этого репозитория, чтобы
`scripts/install-deps.sh` мог их скопировать автоматически.

Если шрифт не установлен, CSS использует fallback: Inter → Cantarell → Sans.
