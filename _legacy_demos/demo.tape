# Generates docs/demo.gif with VHS: https://github.com/charmbracelet/vhs
#
#   pip install agent-chronicle      # so `import chronicle` resolves
#   vhs docs/demo.tape               # writes docs/demo.gif
#
# Then reference it at the top of the README:
#   ![Chronicle demo](docs/demo.gif)

Output docs/demo.gif

Set Shell "bash"
Set FontSize 20
Set Width 1100
Set Height 600
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms

Type "python docs/demo.py"
Sleep 600ms
Enter
Sleep 4500ms
