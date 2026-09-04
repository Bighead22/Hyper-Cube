import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

public class RunPython {
    public static void main(String[] args) {
        try {
            
            String pythonPath = "python";
            String scriptPath = "src/main.py";
            String arg1 = "Hello";
            String arg2 = "World";

            List<String> command = new ArrayList<>();
            command.add(pythonPath);
            command.add(scriptPath);
            command.add(arg1);
            command.add(arg2);

            // 2. Create the ProcessBuilder
            ProcessBuilder pb = new ProcessBuilder(command);
            
            
            pb.redirectErrorStream(true); 

            
            Process process = pb.start();

            
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line;
            System.out.println("--- Python Output Start ---");
            while ((line = reader.readLine()) != null) {
                System.out.println(line);
            }
            System.out.println("--- Python Output End ---");

            
            int exitCode = process.waitFor();
            System.out.println("Process exited with code: " + exitCode);

        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}