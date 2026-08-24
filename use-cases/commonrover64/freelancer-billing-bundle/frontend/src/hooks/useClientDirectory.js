import { useEffect, useMemo, useState } from "react";
import { listClients } from "../services/api.js";

const PAGE_SIZE = 10;

// fetches all clients once, then handles search filtering and pagination
// entirely client-side. Simple for demo-scale dataset, no backend query params needed.
export function useClientDirectory() {
    const [clients, setClients] = useState([]);
    const [searchTerm, setSearchTerm] = useState("");
    const [page, setPage] = useState(1);
    const [error, setError] = useState(null);

    function refreshClients() {
        return listClients()
            .then(setClients)
            .catch((err) => setError(err.message));
    }

    useEffect(() => {
        refreshClients();
    }, []);

    const filteredClients = useMemo(() => {
        const term = searchTerm.trim().toLowerCase();
        if (!term) return clients;
        return clients.filter(
            (c) =>
                c.name?.toLowerCase().includes(term) ||
                c.email?.toLowerCase().includes(term),
        );
    }, [clients, searchTerm]);

    const totalPages = Math.max(
        1,
        Math.ceil(filteredClients.length / PAGE_SIZE),
    );

    // reset to page 1 whenever the search term changes, so the user isn't
    // stranded on a page that no longer has any matching results.
    useEffect(() => {
        setPage(1);
    }, [searchTerm]);

    const pagedClients = useMemo(() => {
        const start = (page - 1) * PAGE_SIZE;
        return filteredClients.slice(start, start + PAGE_SIZE);
    }, [filteredClients, page]);

    return {
        clients,
        pagedClients,
        searchTerm,
        setSearchTerm,
        page,
        setPage,
        totalPages,
        error,
        refreshClients,
    };
}
