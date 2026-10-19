{
  description = "tmux plugin that restores Claude Code conversations with tmux-resurrect";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    resurrect = {
      url = "github:tmux-plugins/tmux-resurrect";
      flake = false;
    };
    tpm = {
      url = "github:tmux-plugins/tpm";
      flake = false;
    };
  };

  outputs =
    {
      nixpkgs,
      resurrect,
      tpm,
      ...
    }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      forSystem =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          runtime = with pkgs; [
            bash
            tmux
            jq
            coreutils
          ];
          testTools =
            with pkgs;
            [
              python3
              git
              gnused
              gnugrep
              gawk
              findutils
            ]
            ++ lib.optionals stdenv.hostPlatform.isLinux [ procps ];
          qualityTools = with pkgs; [
            actionlint
            nixfmt
            shellcheck
            shfmt
            ruff
          ];
          package = pkgs.callPackage ./package.nix { };
          scripts = "claude-tmux-resurrect.tmux bin/* lib/*.sh";
          check =
            name: deps: command:
            pkgs.runCommand name { nativeBuildInputs = deps; } ''
              cp -R ${./.} project
              chmod -R u+w project
              cd project
              ${command}
              touch "$out"
            '';
          behavior = ''
            # Darwin's build sandbox cannot execute /usr/bin/env. Patch only
            # disposable test copies; the plugin itself remains portable.
            patchShebangs --build claude-tmux-resurrect.tmux bin
            cp -R ${resurrect} "$TMPDIR/resurrect"
            cp -R ${tpm} "$TMPDIR/tpm"
            chmod -R u+w "$TMPDIR/resurrect" "$TMPDIR/tpm"
            patchShebangs --build "$TMPDIR/resurrect" "$TMPDIR/tpm"
            export RESURRECT_SOURCE="$TMPDIR/resurrect" TPM_SOURCE="$TMPDIR/tpm"
            python3 -m unittest discover -s tests -v -f
          '';
          individualChecks = {
            formatting = check "formatting" qualityTools ''
              nixfmt --check *.nix
              shfmt -d -i 2 -ci ${scripts}
              ruff format --check tests
            '';
            lint = check "lint" (runtime ++ qualityTools) ''
              shellcheck -x ${scripts}
              ruff check tests
              jq -e . .claude-plugin/plugin.json hooks/hooks.json >/dev/null
              actionlint .github/workflows/*.yml
            '';
            behavior = check "behavior" (runtime ++ testTools) behavior;
            packaging = check "packaging" (runtime ++ testTools) ''
              export PLUGIN_ROOT=${package}/share/tmux-plugins/claude-tmux-resurrect
              ${behavior}
            '';
            nonflake =
              let
                pinnedPackage = import ./default.nix { inherit system; };
                suppliedPackage = import ./default.nix { inherit pkgs; };
              in
              assert pkgs.lib.assertMsg (
                pinnedPackage.drvPath == package.drvPath
              ) "default.nix and the flake must build the same pinned package";
              assert pkgs.lib.assertMsg (
                suppliedPackage.drvPath == package.drvPath
              ) "default.nix must support a caller-supplied pkgs";
              pkgs.linkFarm "nonflake-package" [
                {
                  name = "package";
                  path = pinnedPackage;
                }
              ];
          };
        in
        {
          packages = {
            default = package;
            claude-tmux-resurrect = package;
          };
          checks = individualChecks // {
            all = pkgs.linkFarm "checks-${system}" (
              pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) individualChecks
            );
          };
          devShells.default = pkgs.mkShell {
            packages =
              runtime
              ++ testTools
              ++ qualityTools
              ++ [
                pkgs.nix
                pkgs.direnv
              ];
            RESURRECT_SOURCE = "${resurrect}";
            TPM_SOURCE = "${tpm}";
          };
          formatter = pkgs.nixfmt;
        };
    in
    {
      packages = eachSystem (system: (forSystem system).packages);
      checks = eachSystem (system: (forSystem system).checks);
      devShells = eachSystem (system: (forSystem system).devShells);
      formatter = eachSystem (system: (forSystem system).formatter);
    };
}
