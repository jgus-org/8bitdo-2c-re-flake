import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Reference;

// Lists references to the address given as arg0 (hex). Requires an analyzed program.
public class FindXrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        long t = Long.parseLong(getScriptArgs()[0].toLowerCase().replace("0x", ""), 16);
        Address a = toAddr(t);
        for (Reference r : getReferencesTo(a)) {
            println("XREF " + r.getFromAddress() + " -> " + a + " (" + r.getReferenceType() + ")");
        }
    }
}
