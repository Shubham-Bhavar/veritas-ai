package ai.veritas.document;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.UUID;

import org.springframework.stereotype.Component;

import ai.veritas.config.AppProperties;

/**
 * Uploaded files live under STORAGE_DIR/{investigation}/{document}.bin. Paths are built only
 * from server-generated UUIDs, so a client-supplied filename can never choose where a file goes.
 */
@Component
public class FileStorage {

    private final Path root;

    public FileStorage(AppProperties props) {
        this.root = Path.of(props.storage().dir()).toAbsolutePath().normalize();
        try {
            Files.createDirectories(root);
        } catch (IOException e) {
            throw new UncheckedIOException("Cannot create storage directory " + root, e);
        }
    }

    public Path save(UUID investigationId, UUID documentId, InputStream in) throws IOException {
        Path dir = root.resolve(investigationId.toString());
        Files.createDirectories(dir);
        Path target = dir.resolve(documentId + ".bin");
        Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
        return target;
    }

    public Path resolve(String storagePath) {
        Path p = Path.of(storagePath).toAbsolutePath().normalize();
        if (!p.startsWith(root)) {
            throw new IllegalStateException("Stored path escapes the storage root");
        }
        return p;
    }

    public void delete(String storagePath) {
        try {
            Files.deleteIfExists(resolve(storagePath));
        } catch (IOException | IllegalStateException ignored) {
            // best effort
        }
    }

    public void deleteInvestigation(UUID investigationId) {
        Path dir = root.resolve(investigationId.toString());
        if (!Files.isDirectory(dir)) {
            return;
        }
        try (var files = Files.list(dir)) {
            files.forEach(f -> {
                try {
                    Files.deleteIfExists(f);
                } catch (IOException ignored) {
                    // best effort
                }
            });
            Files.deleteIfExists(dir);
        } catch (IOException ignored) {
            // best effort
        }
    }
}
