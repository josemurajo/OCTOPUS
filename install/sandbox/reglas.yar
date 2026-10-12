// OCTOPUS - reglas YARA basicas para la sala de analisis (amplialas con las tuyas)
rule Nota_de_rescate {
  meta: descripcion = "Texto tipico de notas de rescate"
  strings:
    $a = "your files have been encrypted" nocase
    $b = "bitcoin" nocase
    $c = "decrypt" nocase
    $d = "tor browser" nocase
    $e = ".onion" nocase
    $f = "pagar" nocase
    $g = "rescate" nocase
  condition: 2 of them
}
rule Ejecutable_Windows { strings: $mz = { 4D 5A } condition: $mz at 0 }
rule Ejecutable_Linux { strings: $elf = { 7F 45 4C 46 } condition: $elf at 0 }
rule PowerShell_ofuscado {
  strings:
    $a = "-enc" nocase
    $b = "FromBase64String" nocase
    $c = "IEX" nocase
    $d = "DownloadString" nocase
    $e = "-nop" nocase
  condition: 2 of them
}
rule Borrado_de_copias_sombra {
  meta: descripcion = "Tecnica habitual de ransomware para impedir la recuperacion"
  strings:
    $a = "vssadmin delete shadows" nocase
    $b = "wbadmin delete catalog" nocase
    $c = "bcdedit /set {default} recoveryenabled no" nocase
    $d = "shadowcopy delete" nocase
  condition: any of them
}
