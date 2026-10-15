{
  system ? builtins.currentSystem,
  pkgs ?
    import
      (
        let
          lock = builtins.fromJSON (builtins.readFile ./flake.lock);
          inherit (lock.nodes.nixpkgs.locked)
            owner
            repo
            rev
            narHash
            ;
        in
        builtins.fetchTarball {
          url = "https://github.com/${owner}/${repo}/archive/${rev}.tar.gz";
          sha256 = narHash;
        }
      )
      {
        inherit system;
        config = { };
        overlays = [ ];
      },
}:
pkgs.callPackage ./package.nix { }
