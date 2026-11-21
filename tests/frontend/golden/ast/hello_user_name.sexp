(program
  (expr (call println "What is your name?"))
  (expr (call print "> "))
  (var_decl str name (call input))
  (expr (call println (+ (+ "Hello, " (identifier name)) "!"))))
