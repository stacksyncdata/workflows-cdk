with import <nixpkgs> {
  config = {
  };
};
  mkShell {
    name = "impurePythonEnv";
    buildInputs = [
      # Python
      python311Packages.python
      python311Packages.psycopg2
      python311Packages.python-dotenv
      python311Packages.pip
      python311Packages.pillow
      python311Packages.numpy
      python311Packages.venvShellHook
    ];

    venvDir = "./.venv";
    postVenvCreation = ''
      pip install -r requirements.txt
    '';

    postShellHook = ''
      export SOURCE_DATE_EPOCH=315532800
    '';

    preferLocalBuild = true;
  }
