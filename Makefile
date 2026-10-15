PREFIX ?= $(HOME)/.local
DESTDIR ?=
SCRIPTS := claude-tmux-resurrect-hook claude-tmux-resurrect-save \
	claude-tmux-resurrect-pre-restore claude-tmux-resurrect-post-restore \
	claude-tmux-resurrect-arm claude-tmux-resurrect-setup

.PHONY: install uninstall
install:
	install -d "$(DESTDIR)$(PREFIX)/bin" "$(DESTDIR)$(PREFIX)/share/claude-tmux-resurrect/examples"
	install -m 755 $(addprefix bin/,$(SCRIPTS)) "$(DESTDIR)$(PREFIX)/bin/"
	install -m 644 share/claude-tmux-resurrect/lib.sh LICENSE.md "$(DESTDIR)$(PREFIX)/share/claude-tmux-resurrect/"
	install -m 644 examples/* "$(DESTDIR)$(PREFIX)/share/claude-tmux-resurrect/examples/"

uninstall:
	$(foreach script,$(SCRIPTS),rm -f "$(DESTDIR)$(PREFIX)/bin/$(script)";)
	rm -rf "$(DESTDIR)$(PREFIX)/share/claude-tmux-resurrect"
