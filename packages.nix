{
  lib,
  stdenvNoCC,
  tmuxPlugins,
  makeWrapper,
  bash,
  tmux,
  jq,
  coreutils,
}:
let
  inherit (lib.importJSON ./.claude-plugin/plugin.json) version;
  # Both plugins read their version from the manifest, and either can run the
  # check and show notices.
  source =
    files:
    lib.fileset.toSource {
      root = ./.;
      fileset = lib.fileset.unions (
        [
          ./.claude-plugin/plugin.json
          ./bin/claude-tmux-resurrect-check
          ./bin/claude-tmux-resurrect-notify
          ./docs
          ./lib
          ./LICENSE.md
        ]
        ++ files
      );
    };
  # tmux and Claude run these scripts by path with their own PATH.
  wrapScripts = scripts: ''
    for script in ${scripts}; do
      wrapProgram "$script" --prefix PATH : ${
        lib.makeBinPath [
          bash
          tmux
          jq
          coreutils
        ]
      }
    done
  '';
  meta = {
    homepage = "https://github.com/kallisti-dev/claude-tmux-resurrect";
    license = lib.licenses.bsd3;
    platforms = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
in
{
  tmux-plugin = tmuxPlugins.mkTmuxPlugin {
    pluginName = "claude-tmux-resurrect";
    # The default file name replaces hyphens with underscores.
    rtpFilePath = "claude-tmux-resurrect.tmux";
    inherit version;
    # Without the Claude Code hooks, setup leaves CLAUDE_CODE_PLUGIN_DIRS
    # alone and the Claude plugin is installed separately.
    src = source [
      ./claude-tmux-resurrect.tmux
      ./bin/claude-tmux-resurrect-arm
      ./bin/claude-tmux-resurrect-post-restore
      ./bin/claude-tmux-resurrect-pre-restore
      ./bin/claude-tmux-resurrect-save
      ./bin/claude-tmux-resurrect-setup
    ];
    nativeBuildInputs = [ makeWrapper ];
    # mkTmuxPlugin sets strictDeps, so patchShebangs finds bash only here.
    buildInputs = [ bash ];
    postInstall = wrapScripts ''"$out"/share/tmux-plugins/claude-tmux-resurrect/{claude-tmux-resurrect.tmux,bin/*}'';
    meta = meta // {
      description = "tmux plugin that restores Claude Code conversations with tmux-resurrect";
    };
  };

  claude-plugin = stdenvNoCC.mkDerivation {
    pname = "claude-tmux-resurrect-claude-plugin";
    inherit version;
    src = source [
      ./bin/claude-tmux-resurrect-hook
      ./hooks
      ./skills
    ];
    strictDeps = true;
    nativeBuildInputs = [ makeWrapper ];
    buildInputs = [ bash ];
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      cp -R . "$out"
      ${wrapScripts ''"$out"/bin/*''}
      runHook postInstall
    '';
    meta = meta // {
      description = "Claude Code plugin with the session hooks for the claude-tmux-resurrect tmux plugin";
    };
  };
}
